import re
from collections.abc import Callable
from typing import Any


class WildcardResolver:
    """
    负责 {var} 的渲染
    """

    _pattern = re.compile(r"\{(\w+)\}")

    def __init__(self):
        self._providers: dict[str, Callable[[dict], Any]] = {}

    def register(self, name: str, provider: Callable[[dict], Any]):
        """
        注册一个通配符
        provider(ctx) -> Any
        """
        self._providers[name] = provider

    def render(self, text: str, ctx: dict) -> str:
        """
        渲染提示词内容
        """

        def repl(m: re.Match):
            key = m.group(1)
            fn = self._providers.get(key)
            if not fn:
                return m.group(0)  # 未定义的通配符原样保留
            try:
                value = fn(ctx)
                return "" if value is None else str(value)
            except Exception:
                return m.group(0)

        return self._pattern.sub(repl, text)
