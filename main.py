# plugin.py

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.star import Star
from astrbot.core.star.context import Context
from astrbot.core.star.filter.permission import PermissionType

from .core.config import PluginConfig
from .core.editor import LoreEditor
from .core.entry import LoreEntry
from .core.lorebook import Lorebook
from .core.scheduler import LoreCronScheduler
from .core.session import SessionCache
from .core.share import LorebookShare
from .core.wildcard import WildcardResolver


class WorldBookPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)

        self.cfg = PluginConfig(config)
        self.lorebook = Lorebook(self.cfg)
        self.share = LorebookShare(self.lorebook, self.cfg)
        self.sessions = SessionCache(self.cfg)
        self.style = None
        self.cron = LoreCronScheduler(self.lorebook, self.sessions)
        self.wildcards = WildcardResolver()

    # ================= 生命周期 =================

    async def initialize(self):
        """加载插件时调用"""
        await self.lorebook.initialize()
        self.cron.start()

        try:
            import pillowmd

            self.style = pillowmd.LoadMarkdownStyles(self.cfg.style_dir)
        except Exception as e:
            logger.error(f"无法加载pillowmd样式：{e}")

        self.editor = LoreEditor(self.cfg, self.lorebook, self.sessions, self.style)

    async def terminate(self):
        """插件卸载时调用"""
        self.cron.shutdown()

    # ================= 全局态命令 =================

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("查看条目")
    async def view_entry(self, event: AstrMessageEvent, arg: str | None = None):
        """查看条目（全部 / 启用 / 禁用 / 单个）"""
        async for msg in self.editor.view_entry(event, arg):
            await event.send(msg)

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("添加条目")
    async def add_entry(self, event: AstrMessageEvent, name: str):
        """添加条目 <名称> <内容>"""
        async for msg in self.editor.add_entry(event, name):
            await event.send(msg)

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("删除条目")
    async def delete_entry(self, event: AstrMessageEvent):
        """删除条目 <名称1> <名称2>"""
        async for msg in self.editor.delete_entry(event):
            await event.send(msg)

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("设置触发词")
    async def set_keywords(self, event: AstrMessageEvent):
        """设置触发词 <关键词|正则表达式>"""
        async for msg in self.editor.set_keywords(event):
            await event.send(msg)

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("设置优先级")
    async def set_priority(self, event: AstrMessageEvent):
        """设置优先级 <数字>"""
        async for msg in self.editor.set_priority(event):
            await event.send(msg)

    # ================= 会话态命令 =================

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("启用条目")
    async def enable_entry(self, event: AstrMessageEvent):
        """启用条目 <名称1> <名称2>"""
        async for msg in self.editor.enable_entry(event):
            await event.send(msg)

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("禁用条目")
    async def disable_entry(self, event: AstrMessageEvent):
        """禁用条目 <名称1> <名称2>"""
        async for msg in self.editor.disable_entry(event):
            await event.send(msg)

    @filter.command("条目状态")
    async def entries_state(self, event: AstrMessageEvent):
        """查看当前会话的条目状态"""
        async for msg in self.editor.entries_state(event):
            await event.send(msg)

    @filter.command("清除条目", alias={"清空条目"})
    async def clear_entries(self, event: AstrMessageEvent):
        """清除当前会话的某个条目，默认清除全部"""
        async for msg in self.editor.clear_entries(event):
            await event.send(msg)

    # ================= 文件流通 =================

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("导出世界书")
    async def upload_lorebook(self, event: AstrMessageEvent, name: str | None = None):
        async for msg in self.share.upload_lorebook(event, name):
            yield msg

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("导入世界书")
    async def import_lorebook(self, event: AstrMessageEvent):
        async for msg in self.share.download_lorebook(event):
            yield msg

    # ================= 核心机制 =================

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        """
        LLM 请求主入口

        执行顺序：
        1. 判决并挂载符合条件的条目
        2. 使用当前会话中的条目构造 system_prompt
        """
        msg = event.message_str
        if not msg:
            return

        umo = event.unified_msg_origin

        # Step 1：判决 + 挂载
        self._decide_entries(event, msg, umo)

        # Step 2：使用会话中的条目
        self._consume_entries(event, req, umo)

    def _decide_entries(self, event, msg: str, umo: str) -> None:
        """
        判决与挂载阶段

        职责：
        - 遍历所有可用的 LoreEntry
        - 通过 LoreEntry.can_activate 做统一判决
        - 将通过判决的条目写入 Session
        """

        gid = event.get_group_id()
        uid = event.get_sender_id()
        is_admin = event.is_admin()

        candidates: list[LoreEntry] = []

        for e in self.lorebook.entries:
            # 所有是否“允许进入会话”的判断
            # 必须统一由 LoreEntry.can_activate 给出
            if e.check_activate(
                text=msg,
                user_id=uid,
                group_id=gid,
                session_id=umo,
                is_admin=is_admin,
            ):
                candidates.append(e)

        if not candidates:
            return

        # 将通过判决的条目写入 Session
        self.sessions.attach(umo, candidates)

    def _consume_entries(
        self, event: AstrMessageEvent, req: ProviderRequest, umo: str
    ) -> None:
        """
        使用阶段

        职责：
        - 读取当前会话中已有的条目
        - 按 priority 排序并裁剪
        - 将内容注入 system_prompt
        - 记录一次使用消耗
        """

        # 获取当前会话中仍然存在的条目
        entries = self.sessions.get_sorted_active(umo)
        if not entries:
            return

        uid = event.get_sender_id()
        gid = event.get_group_id()
        is_admin = event.is_admin()

        # === 使用阶段 scope gate ===
        scoped_entries: list[LoreEntry] = []
        for e in entries:
            if e.allow_consume(
                user_id=uid,
                group_id=gid,
                session_id=umo,
                is_admin=is_admin,
            ):
                scoped_entries.append(e)
            else:
                logger.debug(f"[条目:{e.name}] 使用阶段 scope 不满足，已跳过")

        if not scoped_entries:
            return

        # 注入数量限制：
        # - 越靠前的条目影响越大
        # - 超出部分仅在本次请求中被忽略
        max_count = self.cfg.max_inject_count
        logger.debug(f"当前会话可用条目：{[e.name for e in entries]}")
        if max_count > 0 and len(entries) > max_count:
            dropped = entries[max_count:]
            logger.debug(
                f"超出最大允许注入数 {max_count}，"
                f"已忽略 [{', '.join(e.name for e in dropped)}]"
            )
            entries = entries[:max_count]

        if not entries:
            return

        sections: list[str] = []

        for entry in entries:
            title = f"## [{entry.name}]"
            rendered = self.wildcards.render(entry, event)
            sections.append(f"{title}\n{rendered}")

            # 一次注入视为一次使用
            entry.on_consume()

        req.system_prompt += "\n\n" + "\n\n".join(sections) + "\n\n"
