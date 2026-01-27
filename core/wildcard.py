import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from astrbot.core.platform.astr_message_event import AstrMessageEvent

from .entry import LoreEntry

# ===== 1) 内置上下文：无参实例化，放“规则/工具/派生逻辑” =====


class BuiltinContext:
    """
    内置上下文：不承载实时数据，不需要传参实例化。
    你未来扩展“内置能力”都往这里加。
    """

    # 你也可以放一些常量、格式、开关等
    time_format = "%H:%M:%S"

    def now_time(self) -> str:
        return datetime.now().strftime(self.time_format)

    def format_user(self, user_name: str | None, user_id: str | None) -> str:
        # 统一的 user 展示规则
        name = user_name or ""
        uid = user_id or ""
        if name and uid:
            return f"{name}({uid})"
        return name or uid


# ===== 2) 实时上下文：每次 render 构造，放 entry/event 等 =====


@dataclass(frozen=True)
class RuntimeContext:
    entry: LoreEntry
    event: AstrMessageEvent


# ===== 3) 视图上下文：把 Builtin + Runtime 合成统一读取口 =====


class ResolveView:
    """
    通配符解析时使用的只读视图：
    - 既能访问 runtime 的实时数据
    - 又能访问 builtin 的内置能力
    """

    def __init__(self, builtin: BuiltinContext, runtime: RuntimeContext):
        self.builtin = builtin
        self.runtime = runtime

    # ---- 常用字段（写 Lore 时最常用的名字）----

    @property
    def user_id(self):
        return self.runtime.event.get_sender_id()

    @property
    def user_name(self):
        return self.runtime.event.get_sender_name()

    @property
    def user(self):
        return self.builtin.format_user(self.user_name, self.user_id)

    @property
    def time(self):
        return self.builtin.now_time()

    # ---- 直接暴露 entry（便于 {entry_name} 这类别名也能做）----

    @property
    def entry_name(self):
        return getattr(self.runtime.entry, "name", None)


# ===== 4) Resolver：对外只给 render；注册不暴露 =====


class WildcardResolver:
    _pattern = re.compile(r"\{(\w+)\}")

    def __init__(self):
        self._builtin = BuiltinContext()  # ✅ 无参实例化
        self._providers: dict[str, Callable[[ResolveView], Any]] = {}
        self._register_builtin_providers()

    # 内部注册：不对外暴露
    def _register(self, name: str, provider: Callable[[ResolveView], Any]):
        self._providers[name] = provider

    def _register_builtin_providers(self):
        """
        只放“必须用 provider 的东西”：
        - 需要计算
        - 需要容错/分支
        - 需要兼容旧变量名
        """
        # 例：兼容旧写法 {user_name}/{user_id} 其实也可以不注册，
        # 但注册可用于别名/兼容/复杂逻辑。
        self._register("user_id", lambda v: v.user_id)
        self._register("user_name", lambda v: v.user_name)
        self._register("user", lambda v: v.user)
        self._register("time", lambda v: v.time)

        # 例：你想加更多内置变量，直接在这里 _register 即可
        # self._register("entry_name", lambda v: v.entry_name)

    def render(self, entry: LoreEntry, event: AstrMessageEvent) -> str:
        runtime = RuntimeContext(entry=entry, event=event)
        view = ResolveView(self._builtin, runtime)
        text = entry.content

        def repl(m: re.Match):
            key = m.group(1)

            # 1) provider 优先（可做兼容/复杂逻辑/别名）
            fn = self._providers.get(key)
            if fn is not None:
                try:
                    val = fn(view)
                    return "" if val is None else str(val)
                except Exception:
                    return m.group(0)

            # 2) 其次：允许直接读 view 上的属性
            if hasattr(view, key):
                try:
                    val = getattr(view, key)
                    return "" if val is None else str(val)
                except Exception:
                    return m.group(0)

            return m.group(0)

        return self._pattern.sub(repl, text)
