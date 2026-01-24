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

    def remove(self, umo: str, names: list[str]) -> list[str]:
        """
        从会话中移除指定名称的 prompts
        返回成功移除的 prompt 名称
        """
        prompts = self._data.get(umo)
        if not prompts:
            return []

        names_set = set(names)
        remain: list[PromptItem] = []
        removed: list[str] = []

        for p in prompts:
            if p.name in names_set:
                removed.append(p.name)
            else:
                remain.append(p)

        if remain:
            self._data[umo] = remain
        else:
            self._data.pop(umo, None)

        return removed

    def activate(self, umo: str, prompts: list[PromptItem]) -> None:
        """
        激活一组 prompt 到会话中（按 priority 管理）。

        规则：
        - 会话内以 prompt.priority 为唯一键
        - 新触发的 prompt 覆盖同 priority 的旧 prompt（重新激活）
        - 不同 priority 的 prompt 会叠加存在
        - 覆盖会重置激活时间与注入次数
        """
        now = time.time()

        # 1. 取出当前会话中仍然有效的 prompts
        old_prompts = self._data.get(umo, [])
        old_prompts = [p for p in old_prompts if p.available]

        # 2. 用 priority 作为唯一 key
        prompt_map: dict[int, PromptItem] = {p.priority: p for p in old_prompts}

        # 3. 新触发的 prompt 覆盖同 priority 的旧 prompt
        for p in prompts:
            ap = copy.deepcopy(p)  # 必须 deepcopy
            ap._activated_at = now
            ap._inject_count = 0  # 显式重置（更清晰）

            prompt_map[p.priority] = ap

        # 4. 写回 session
        self._data[umo] = list(prompt_map.values())

    def deactivate(self, umo: str) -> None:
        """
        强制清除会话的所有prompts
        """
        self._data.pop(umo, None)
