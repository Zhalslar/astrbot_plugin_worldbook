# plugin.py
import asyncio

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.star import Star
from astrbot.core.star.context import Context

from .core.config import PluginConfig
from .core.prompt import PromptManager
from .core.session import SessionCache


class WorldBookPlugin(Star):

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.cfg = PluginConfig(config)
        self.prompt_mgr = PromptManager(self.cfg)
        self.sessions = SessionCache()

    async def initialize(self):
        asyncio.create_task(asyncio.to_thread(self.load_prompt_files))

    def load_prompt_files(self) -> None:
        """依次加载 cfg.prompt_files 中的路径"""
        for file in self.cfg.prompt_files:
            try:
                self.prompt_mgr.load_prompts_from_file(file, override=False)
            except Exception as e:
                logger.error(f"[prompt] load failed: {file} ({e})")

    @filter.command("查看提示词")
    async def view_prompt(self, event: AstrMessageEvent, arg: str | None = None):
        """查看提示词（全部 / 启用 / 禁用 / 单个）"""
        if arg == "启用":
            prompts = self.prompt_mgr.list_enabled_prompts()
        elif arg == "禁用":
            prompts = self.prompt_mgr.list_disabled_prompts()
        elif arg:
            prompt = self.prompt_mgr.get_prompt(arg)
            prompts = [prompt] if prompt else []
        else:
            prompts = self.prompt_mgr.list_prompts()

        if not prompts:
            yield event.plain_result("未找到任何提示词")
            return

        prompts = sorted(prompts, key=lambda p: p.priority)
        blocks = [p.display() for _, p in enumerate(prompts, start=1)]
        yield event.plain_result("\n\n\n\n".join(blocks))

    @filter.command("添加提示词")
    async def add_prompt(self, event: AstrMessageEvent, name: str):
        """添加一个简单提示词（name + 当前消息内容）"""
        if len(name) > 10:
            yield event.plain_result("提示词名称过长")
            return
        content = event.message_str.removeprefix(f"添加提示词 {name}").strip()
        if not content:
            yield event.plain_result("请输入提示词内容")
            return
        try:
            p = self.prompt_mgr.add_prompt(name=name, content=content)
            msg = f"新增提示词：{p.name} \n触发优先级: {p.priority}"
            yield event.plain_result(msg)
        except Exception as e:
            logger.error(e)
            yield event.plain_result(f"提示词添加失败：{e}")

    @filter.command("删除提示词")
    async def delete_prompt(self, event: AstrMessageEvent):
        """按 name 删除提示词（支持多个）"""
        names = event.message_str.split()[1:]
        if not names:
            yield event.plain_result("请指定要删除的提示词名称")
            return

        ok, fail = self.prompt_mgr.remove_prompts(names)

        lines = []
        if ok:
            lines.append("🗑 已删除：" + ", ".join(ok))
        if fail:
            lines.append("❌ 未找到：" + ", ".join(fail))

        yield event.plain_result("\n".join(lines))

    @filter.command("启用提示词")
    async def enable_prompt(self, event: AstrMessageEvent):
        """按 name 启用提示词（支持多个）"""
        names = event.message_str.split()[1:]
        if not names:
            yield event.plain_result("请指定要启用的提示词名称")
            return

        ok, fail = self.prompt_mgr.enable_prompts(names)

        lines = []
        if ok:
            lines.append("已启用：" + ", ".join(ok))
        if fail:
            lines.append("未找到：" + ", ".join(fail))

        yield event.plain_result("\n".join(lines))

    @filter.command("禁用提示词")
    async def disable_prompt(self, event: AstrMessageEvent):
        """按 name 禁用提示词（支持多个）"""
        names = event.message_str.split()[1:]
        if not names:
            yield event.plain_result("请指定要禁用的提示词名称")
            return

        ok, fail = self.prompt_mgr.disable_prompts(names)

        lines = []
        if ok:
            lines.append("已禁用：" + ", ".join(ok))
        if fail:
            lines.append("未找到：" + ", ".join(fail))

        yield event.plain_result("\n".join(lines))

    @filter.command("提示词状态")
    async def on_command(self, event: AstrMessageEvent):
        """查看当前会话的提示词状态"""
        umo = event.unified_msg_origin
        prompts = self.sessions.get(umo)
        if not prompts:
            yield event.plain_result("当前会话未激活任何提示词")
            return

        lines = ["【提示词状态】"]
        for idx, p in enumerate(prompts, start=1):
            if p.times == 0:
                times_text = "不限次数"
            else:
                times_text = f"{p._inject_count}/{p.times} 次"

            time_text = "一直注入" if p.duration == 0 else f"剩余{p.remaining}秒"

            lines.append(f"{idx}. {p.name}（{time_text}，{times_text}）")

        yield event.plain_result("\n".join(lines))

    @filter.command("清除提示词")
    async def stop_inject(self, event: AstrMessageEvent):
        """清除当前会话的某个提示词，默认清除全部"""
        umo = event.unified_msg_origin
        parts = event.message_str.split()
        names = parts[1:]

        if not names:
            self.sessions.deactivate(umo)
            yield event.plain_result("已清除当前会话的所有提示词")
            return

        removed = self.sessions.remove(umo, names)

        if not removed:
            yield event.plain_result("当前会话中未找到指定的提示词")
            return

        msg = f"已清除提示词：{', '.join(removed)}"
        yield event.plain_result(msg)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def message_handler(self, event: AstrMessageEvent):
        """监听用户消息，激活提示词"""
        msg = event.message_str
        if not msg:
            return
        umo = event.unified_msg_origin

        # 匹配提示词
        prompts = self.prompt_mgr.match_prompts(msg)
        if not prompts:
            return

        # 权限过滤
        if not event.is_admin():
            prompts = [p for p in prompts if not self.cfg.is_admin_priority(p.priority)]

        # 激活提示词
        self.sessions.activate(umo, prompts)
        names = ", ".join(p.name for p in prompts)
        logger.debug(f"{umo} 激活 Prompt: {names}")

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        """监听 LLM 请求，注入提示词"""
        umo = event.unified_msg_origin
        prompts = self.sessions.get(umo)
        if not prompts:
            return

        sections = ["## 临时附加状态\n"]

        multi = len(prompts) > 1
        if multi:
            sections.append("> 注意：多个状态间若有逻辑冲突，采用优先级较小者\n")

        for p in sorted(prompts, key=lambda x: x.priority):
            if multi:
                title = f"### 【{p.name}】模式已激活，优先级为 {p.priority}："
            else:
                title = f"### 【{p.name}】模式已激活："

            sections.append(f"{title}\n{p.content}")
            p._inject_count += 1

        req.system_prompt += "\n".join(sections)
