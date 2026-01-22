# core/session.py
from __future__ import annotations

import copy
import time

from .prompt import PromptItem


class SessionCache:
    """会话级 Prompt 缓存"""

    def __init__(self):
        # umo -> active PromptItem list
        self._data: dict[str, list[PromptItem]] = {}

    # ========= 内部工具 =========

    def _cleanup(self, umo: str) -> list[PromptItem] | None:
        prompts = self._data.get(umo)
        if not prompts:
            return None

        prompts = [p for p in prompts if p.available]

        if not prompts:
            self._data.pop(umo, None)
            return None

        self._data[umo] = prompts
        return prompts

    # ========= 对外接口 =========

    def get(self, umo: str) -> list[PromptItem] | None:
        """
        获取当前会话的有效 prompts
        """
        return self._cleanup(umo)

    def activate(self, umo: str, prompts: list[PromptItem]) -> None:
        """
        激活一组 prompt（每个 prompt 独立计时）
        """
        now = time.time()
        active_prompts: list[PromptItem] = []

        for p in prompts:
            ap = copy.copy(p)  # 必须 clone，避免污染配置态
            ap._activated_at = now
            active_prompts.append(ap)

        self._data[umo] = active_prompts

    def deactivate(self, umo: str) -> None:
        """
        强制清除会话
        """
        self._data.pop(umo, None)
