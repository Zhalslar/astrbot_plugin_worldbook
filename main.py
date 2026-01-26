# plugin.py

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.star import Star
from astrbot.core.star.context import Context
from astrbot.core.star.filter.permission import PermissionType

from .core.config import PluginConfig
from .core.entry import LoreEntry
from .core.lorebook import Lorebook
from .core.scheduler import LoreCronScheduler
from .core.session import SessionCache
from .core.share import LorebookShare
from .core.wildcard import WildcardResolver, register_builtin


class WorldBookPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)

        self.cfg = PluginConfig(config)
        self.lorebook = Lorebook(self.cfg)
        self.share = LorebookShare(self.lorebook, self.cfg)
        self.sessions = SessionCache()
        self.wildcards = WildcardResolver()
        self.cron = LoreCronScheduler(self.lorebook, self.sessions)

        register_builtin(self.wildcards)

    # ================= 生命周期 =================

    async def initialize(self):
        """加载插件时调用"""
        await self.lorebook.initialize()
        self.cron.start()

    async def terminate(self):
        """插件卸载时调用"""
        self.cron.shutdown()

    # ================= 全局态命令 =================

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("查看条目")
    async def view_entry(self, event: AstrMessageEvent, arg: str | None = None):
        """查看条目（全部 / 启用 / 禁用 / 单个）"""
        if arg == "启用":
            entries = self.lorebook.list_enabled_entries()
        elif arg == "禁用":
            entries = self.lorebook.list_disabled_entries()
        elif arg:
            entry = self.lorebook.get_entry(arg)
            entries = [entry] if entry else []
        else:
            entries = self.lorebook.list_entries()

        if not entries:
            yield event.plain_result("未找到任何条目")
            return

        entries = sorted(entries, key=lambda e: e.priority)
        blocks = [e.display() for _, e in enumerate(entries, start=1)]
        yield event.plain_result("\n\n\n\n".join(blocks))

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("添加条目")
    async def add_entry(self, event: AstrMessageEvent, name: str):
        """添加条目 <名称> <内容>"""
        if len(name) > 10:
            yield event.plain_result("条目名称过长")
            return
        content = event.message_str.removeprefix(f"添加条目 {name}").strip()
        if not content:
            yield event.plain_result("请输入条目内容")
            return
        try:
            entry = self.lorebook.add_entry(name=name, content=content)
            msg = f"新增条目：{entry.name} \n触发优先级: {entry.priority}"
            yield event.plain_result(msg)
        except Exception as e:
            logger.error(e)
            yield event.plain_result(f"条目添加失败：{e}")

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("删除条目")
    async def delete_entry(self, event: AstrMessageEvent):
        """删除条目 <名称1> <名称2>"""
        names = event.message_str.split()[1:]
        if not names:
            yield event.plain_result("请指定要删除的条目名称")
            return

        ok, fail = self.lorebook.remove_entries(names)

        lines = []
        if ok:
            lines.append("🗑 已删除：" + ", ".join(ok))
        if fail:
            lines.append("❌ 未找到：" + ", ".join(fail))

        yield event.plain_result("\n".join(lines))

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("设置触发词")
    async def set_keywords(self, event: AstrMessageEvent):
        """设置触发词 <关键词|正则表达式>"""
        parts = event.message_str.split()
        if len(parts) < 3:
            yield event.plain_result("用法：设置触发词 名字 规则1 [规则2 ...]")
            return

        name = parts[1]
        keywords = parts[2:]

        ok = self.lorebook.update_keywords(name, keywords)
        if not ok:
            yield event.plain_result(f"未找到条目：{name}")
            return

        yield event.plain_result(f"条目【{name}】触发词已更新，共 {len(keywords)} 条")

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("设置优先级")
    async def set_priority(self, event: AstrMessageEvent):
        """设置优先级 <数字>"""
        parts = event.message_str.split()
        if len(parts) != 3:
            yield event.plain_result("用法：设置优先级 名字 数字")
            return

        name = parts[1]
        try:
            priority = int(parts[2])
        except ValueError:
            yield event.plain_result("优先级必须是整数")
            return

        ok = self.lorebook.update_priority(name, priority)
        if not ok:
            yield event.plain_result(f"未找到条目：{name}")
            return

        yield event.plain_result(f"条目【{name}】优先级已设置为 {priority}")

    # ================= 会话态命令 =================

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("启用条目")
    async def enable_entry(self, event: AstrMessageEvent):
        """启用条目 <名称1> <名称2>"""
        names = event.message_str.split()[1:]
        if not names:
            yield event.plain_result("用法：启用条目 名称1 [名称2 ...]")
            return

        umo = event.unified_msg_origin
        ok, fail = [], []

        for name in names:
            if not self.lorebook.get_entry(name):
                fail.append(name)
                continue
            self.lorebook.add_scope_to_entry(name, umo)
            ok.append(name)

        lines = []
        if ok:
            lines.append(f"当前会话已启用：{', '.join(ok)}")
        if fail:
            lines.append("未找到：" + ", ".join(fail))
        yield event.plain_result("\n".join(lines))

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("禁用条目")
    async def disable_entry(self, event: AstrMessageEvent):
        """禁用条目 <名称1> <名称2>"""
        names = event.message_str.split()[1:]
        if not names:
            yield event.plain_result("用法：禁用条目 名称1 [名称2 ...]")
            return

        umo = event.unified_msg_origin
        ok, fail = [], []

        for name in names:
            if not self.lorebook.get_entry(name):
                fail.append(name)
                continue
            self.lorebook.remove_scope_from_entry(name, umo)
            ok.append(name)

        # 同时把当前会话里已激活的也清掉，避免“禁用了但本次还在注入”
        self.sessions.remove(umo, ok)

        lines = []
        if ok:
            lines.append(f"当前会话已禁用：{', '.join(ok)}")
        if fail:
            lines.append("未找到：" + ", ".join(fail))
        yield event.plain_result("\n".join(lines))

    @filter.command("条目状态")
    async def on_command(self, event: AstrMessageEvent):
        """查看当前会话的条目状态"""
        umo = event.unified_msg_origin
        entries = self.sessions.get(umo)
        if not entries:
            yield event.plain_result("当前会话未激活任何条目")
            return

        lines = ["【条目状态】"]
        for idx, e in enumerate(entries, start=1):
            if e.times == 0:
                times_text = "不限次数"
            else:
                times_text = f"{e._inject_count}/{e.times} 次"

            time_text = "一直注入" if e.duration == 0 else f"剩余{e.remaining}秒"

            lines.append(f"{idx}. {e.name}（{time_text}，{times_text}）")

        yield event.plain_result("\n".join(lines))

    @filter.command("清除条目", alias={"清空条目"})
    async def stop_inject(self, event: AstrMessageEvent):
        """清除当前会话的某个条目，默认清除全部"""
        umo = event.unified_msg_origin
        parts = event.message_str.split()
        names = parts[1:]

        if not names:
            self.sessions.deactivate(umo)
            yield event.plain_result("已清除当前会话的所有条目")
            return

        removed = self.sessions.remove(umo, names)

        if not removed:
            yield event.plain_result("当前会话中未找到指定的条目")
            return

        msg = f"已清除条目：{', '.join(removed)}"
        yield event.plain_result(msg)

    # ================= 文件流通 =================

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("导出世界书")
    async def upload_lorebook(self, event: AstrMessageEvent, name: str | None = None):
        async for msg in self.share.upload_lorebook(event, name):
            yield msg

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("导入世界书")
    async def import_lorebook(self, event: AstrMessageEvent):
        async for msg in self.share.download_lorebook(event, override=False):
            yield msg

    # ================= 核心机制 =================

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        """监听 LLM 请求，注入条目"""
        msg = event.message_str
        if not msg:
            return

        umo = event.unified_msg_origin

        # 激活阶段
        self._activate_entries(event, msg, umo)

        # 注入阶段
        self._inject_entries(event, req, umo)

    def _activate_entries(self, event, msg: str, umo: str) -> None:
        gid = event.get_group_id()
        uid = event.get_sender_id()
        is_admin = event.is_admin()

        candidates: list[LoreEntry] = []

        for e in self.lorebook.list_enabled_entries():
            # 所有激活决策，统一交给 LoreEntry
            if e.can_activate(
                text=msg,
                user_id=uid,
                group_id=gid,
                session_id=umo,
                is_admin=is_admin,
            ):
                candidates.append(e)

        if not candidates:
            return

        # 激活成功后的收尾逻辑，也交给 LoreEntry
        for e in candidates:
            e.on_activated()

        self.sessions.activate(umo, candidates)
        logger.debug(f"{umo} 激活条目: {', '.join(e.name for e in candidates)}")

    def _inject_entries(
        self, event: AstrMessageEvent, req: ProviderRequest, umo: str
    ) -> None:
        """将当前会话中已激活的条目注入 system_prompt"""

        entries = self.sessions.get(umo)
        if not entries:
            return

        entries = self._prepare_entries_for_injection(entries)
        if not entries:
            return

        ctx = {
            "user_id": event.get_sender_id(),
            "user_name": event.get_sender_name(),
        }

        sections = self._render_entries(entries, ctx)
        req.system_prompt += "\n\n" + "\n\n".join(sections) + "\n\n"

    def _prepare_entries_for_injection(self, entries: list[LoreEntry]) -> list:
        """
        按优先级排序并裁剪条目：
        - priority 数字越小，优先级越高
        - system_prompt 中越靠前，约束力越强
        """

        entries = sorted(entries, key=lambda x: x.priority)

        max_count = self.cfg.max_inject_count
        if max_count > 0 and len(entries) > max_count:
            dropped = entries[max_count:]
            logger.debug(
                f"当前会话共{len(entries)}个条目激活中"
                f"，超出最大允许的注入数 {max_count}"
                f"已自动丢弃 [{', '.join(e.name for e in dropped)}]"
            )
            entries = entries[:max_count]

        return entries

    def _render_entries(self, entries: list[LoreEntry], ctx: dict) -> list[str]:
        """渲染条目内容为 system_prompt 片段"""

        sections: list[str] = []

        for e in entries:
            title = f"## [{e.name}]"
            rendered = self.wildcards.render(e.content, ctx)
            sections.append(f"{title}\n{rendered}")
            e._inject_count += 1

        return sections
