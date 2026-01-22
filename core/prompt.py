# core/prompt.py
from __future__ import annotations

import re
import time

from astrbot.api import logger

from .config import ConfigNode, PluginConfig


class PromptItem(ConfigNode):
    __template_key: str
    name: str
    enable: bool
    regexs: list[str]
    content: str
    duration: int
    times: int
    priority: int
    only_admin: bool
    _activated_at: float | None = None
    _inject_count: int = 0
    _compiled_regexs: list[re.Pattern] = []

    @property
    def activated(self) -> bool:
        return self._activated_at is not None

    @property
    def expired(self) -> bool:
        # 未激活：不算过期
        if self._activated_at is None:
            return False

        # duration == 0：永久生效
        if self.duration == 0:
            return False

        return time.time() >= self._activated_at + self.duration

    @property
    def remaining(self) -> int:
        if self.duration == 0:
            return 0

        if self._activated_at is None:
            return self.duration

        return max(
            0,
            int(self.duration - (time.time() - self._activated_at)),
        )

    @property
    def available(self) -> bool:
        """
        当前 prompt 是否仍可注入
        """
        # 已过期（时间）
        if self.expired:
            return False

        # 次数限制：times == 0 表示不限制
        if self.times > 0 and self._inject_count >= self.times:
            return False

        return True

    def __init__(self, data: dict):
        super().__init__(data)

        self._compiled_regexs = []
        for pattern in self.regexs:
            try:
                self._compiled_regexs.append(re.compile(pattern))
            except re.error as e:
                logger.warning(f"[prompt:{self.name}] 正则编译失败: {pattern} ({e})")


class PromptManager:
    """Prompt 管理器"""

    def __init__(self, config: PluginConfig):
        self.cfg = config
        self.prompts: list[PromptItem] = []
        self._register_prompt()
        self._enabled_prompts_cache: list[PromptItem] = [
            p for p in self.prompts if p.enable
        ]

    def _register_prompt(self):
        for item in self.cfg.prompt_templates:
            prompt = PromptItem(item)
            self.prompts.append(prompt)
            logger.debug(f"已注册 Prompt: {prompt.name}, 参数: {prompt.raw_data()}")

    def get_prompt(self, name: str) -> PromptItem | None:
        for prompt in self.prompts:
            if prompt.name == name:
                return prompt
        return None

    @property
    def enabled_prompts(self) -> list[PromptItem]:
        return self._enabled_prompts_cache

    def enabled_sorted_prompts(self) -> list[PromptItem]:
        return sorted(
            self._enabled_prompts_cache,
            key=lambda p: p.priority,
        )

    def match_prompts(self, text: str) -> list[PromptItem]:
        """
        根据文本匹配 prompt（不处理 priority 规则）
        """
        matched: list[PromptItem] = []

        for prompt in self.enabled_sorted_prompts():
            for regex in prompt._compiled_regexs:
                if regex.search(text):
                    matched.append(prompt)
                    break

        return matched
