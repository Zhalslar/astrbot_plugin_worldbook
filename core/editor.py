from astrbot.api import logger
from astrbot.core.message.components import Image, Plain
from astrbot.core.platform.astr_message_event import AstrMessageEvent

from .config import PluginConfig
from .lorebook import Lorebook
from .session import SessionCache


class LoreEditor:
    def __init__(
        self,
        config: PluginConfig,
        lorebook: Lorebook,
        sessions: SessionCache,
        style=None,
    ):
        self.cfg = config
        self.lorebook = lorebook
        self.sessions = sessions
        self.style = style

    async def style_send(
        self,
        event: AstrMessageEvent,
        content: str,
        *,
        msg: str | None = None,
    ):
        chain = []

        if msg:
            chain.append(Plain(msg))

        if self.style:
            img = await self.style.AioRender(text=content, useImageUrl=True)
            img_path = img.Save(self.cfg.cache_dir)
            chain.append(Image(str(img_path)))
        else:
            chain.append(Plain(content))

        await event.send(event.chain_result(chain))
        event.stop_event()

    # ================= 全局态命令 =================

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
        blocks = [e.display() for e in entries]
        content = "\n\n\n".join(blocks)
        await self.style_send(event, content)

    async def add_entry(self, event: AstrMessageEvent, name: str):
        """添加条目 <名称> <内容>"""
        if len(name) > 10:
            yield event.plain_result("条目名称过长")
            return
        content = event.message_str.removeprefix(f"添加条目 {name}").strip()
        if not content:
            yield event.plain_result("请输入条目内容")
            return
        data = {
            "name": name,
            "content": content,
            "keywords": [name],
        }
        try:
            entry = self.lorebook.add_entry(data)
            msg = f"新增条目：{entry.name} "
            await self.style_send(event, content, msg=msg)
        except Exception as e:
            logger.error(e)
            yield event.plain_result(f"条目添加失败：{e}")

    async def delete_entry(self, event: AstrMessageEvent):
        """删除条目 <名称1> <名称2>"""
        names = event.message_str.split()[1:]
        if not names:
            yield event.plain_result("请指定要删除的条目名称")
            return

        ok, fail = self.lorebook.remove_entries(names)

        lines = []
        if ok:
            lines.append("已删除条目：" + ", ".join(ok))
        if fail:
            lines.append("未找到条目：" + ", ".join(fail))

        yield event.plain_result("\n".join(lines))

    async def set_keywords(self, event: AstrMessageEvent):
        """设置触发词 <关键词|正则表达式>"""
        parts = event.message_str.split()
        if len(parts) < 3:
            yield event.plain_result("用法：设置触发词 条目名 规则1 [规则2 ...]")
            return

        name = parts[1]
        keywords = parts[2:]

        ok = self.lorebook.update_keywords(name, keywords)
        if not ok:
            yield event.plain_result(f"未找到条目：{name}")
            return

        yield event.plain_result(f"条目【{name}】触发词已更新，共 {len(keywords)} 条")

    async def set_priority(self, event: AstrMessageEvent):
        """设置优先级 <数字>"""
        parts = event.message_str.split()
        if len(parts) != 3:
            yield event.plain_result("用法：设置优先级 条目名 数字")
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

    async def entries_state(self, event: AstrMessageEvent):
        """查看当前会话的条目状态"""
        umo = event.unified_msg_origin
        entries = self.sessions.get_sorted_active(umo)
        if not entries:
            yield event.plain_result("当前会话未激活任何条目")
            return

        lines = ["【条目状态】"]
        for idx, e in enumerate(entries, start=1):
            remaining_str = e.display_remaining()
            lines.append(f"{idx}. {remaining_str}")

        yield event.plain_result("\n".join(lines))

    async def clear_entries(self, event: AstrMessageEvent):
        """清除当前会话的某个条目，默认清除全部"""
        umo = event.unified_msg_origin
        parts = event.message_str.split()
        names = parts[1:]

        if not names:
            self.sessions.clear(umo)
            yield event.plain_result("已清除当前会话的所有条目")
            return

        removed = self.sessions.remove(umo, names)

        if not removed:
            yield event.plain_result("当前会话中未找到指定的条目")
            return

        msg = f"已清除条目：{', '.join(removed)}"
        yield event.plain_result(msg)
