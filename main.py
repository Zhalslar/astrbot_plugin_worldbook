# plugin.py
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.star import Star
from astrbot.core.star.context import Context

from .core.config import PluginConfig
from .core.prompt import PromptItem, PromptManager
from .core.session import SessionCache


class PromptInjectPlugin(Star):
    """提示词注入插件"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.cfg = PluginConfig(config)
        self.prompt_mgr = PromptManager(self.cfg)
        self.sessions = SessionCache()

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
            prompts = [p for p in prompts if not p.only_admin]

        # 激活提示词
        self.sessions.activate(umo, prompts)
        names = ", ".join(p.name for p in prompts)
        logger.debug(f"{umo} 激活 Prompt: {names}")

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        """当有 LLM 请求时，将提示词注入到请求中"""
        umo = event.unified_msg_origin
        prompts = self.sessions.get(umo)
        if not prompts:
            return

        for p in prompts:
            if p.available:
                req.system_prompt += f"\n\n{p.content}"
                p._inject_count += 1  # 累加注入次数

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
        """清除当前会话要注入的所有提示词"""
        self.sessions.deactivate(event.unified_msg_origin)

    @filter.command("查看提示词")
    async def view_prompt(self, event: AstrMessageEvent, name: str | None = None):
        """查看某一提示词, 默认查看所有"""
        final: list[PromptItem] = []
        if name:
            if prompt := self.prompt_mgr.get_prompt(name):
                final.append(prompt)
        else:
            final.extend(self.prompt_mgr.prompts)
        if not final:
            yield event.plain_result("未找到任何提示词")
            return
        msg = "\n\n".join(f"【{p.name}】\n{p.content}" for p in final)
        yield event.plain_result(msg)
