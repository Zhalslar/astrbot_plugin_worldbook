# core/session.py
from __future__ import annotations

import copy
import time

from .entry import LoreEntry


class SessionCache:
    """会话级 Prompt 缓存"""

    def __init__(self):
        # umo -> active LoreEntry list
        self._data: dict[str, list[LoreEntry]] = {}

    # ========= 内部工具 =========

    def _cleanup(self, umo: str) -> list[LoreEntry] | None:
        entries = self._data.get(umo)
        if not entries:
            return None

        entries = [e for e in entries if e.available]

        if not entries:
            self._data.pop(umo, None)
            return None

        self._data[umo] = entries
        return entries

    # ========= 对外接口 =========

    def get(self, umo: str) -> list[LoreEntry] | None:
        """
        获取当前会话的有效 prompts
        """
        return self._cleanup(umo)

    def remove(self, umo: str, names: list[str]) -> list[str]:
        """
        从会话中移除指定名称的条目
        返回成功移除的条目名称
        """
        entries = self._data.get(umo)
        if not entries:
            return []

        names_set = set(names)
        remain: list[LoreEntry] = []
        removed: list[str] = []

        for e in entries:
            if e.name in names_set:
                removed.append(e.name)
            else:
                remain.append(e)

        if remain:
            self._data[umo] = remain
        else:
            self._data.pop(umo, None)

        return removed

    def activate(self, umo: str, entries: list[LoreEntry]) -> None:
        """
        激活一组条目到会话中（按 priority 管理）。

        规则：
        - 会话内以 entry.priority 为唯一键
        - 新触发的 prompt 覆盖同 priority 的旧 prompt（重新激活）
        - 不同 priority 的 prompt 会叠加存在
        - 覆盖会重置激活时间与注入次数
        """
        now = time.time()

        # 1. 取出当前会话中仍然有效的 entries
        old_entries = self._data.get(umo, [])
        old_entries = [e for e in old_entries if e.available]

        # 2. 用 priority 作为唯一 key
        entry_map: dict[int, LoreEntry] = {e.priority: e for e in old_entries}

        # 3. 新触发的 prompt 覆盖同 priority 的旧 prompt
        for e in entries:
            ae = copy.deepcopy(e)  # 必须 deepcopy
            ae._activated_at = now
            ae._inject_count = 0  # 显式重置（更清晰）

            entry_map[e.priority] = ae

        # 4. 写回 session
        self._data[umo] = list(entry_map.values())

    def deactivate(self, umo: str) -> None:
        """
        强制清除会话的所有prompts
        """
        self._data.pop(umo, None)
