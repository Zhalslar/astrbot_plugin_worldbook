# core/session.py
from __future__ import annotations

import copy

from astrbot.api import logger

from .config import PluginConfig
from .entry import LoreEntry


class SessionCache:
    """会话级 Prompt 缓存"""

    def __init__(self, config: PluginConfig):
        self.cfg = config
        # umo -> active LoreEntry list
        self._data: dict[str, list[LoreEntry]] = {}

    def get_sorted_active(self, umo: str) -> list[LoreEntry]:
        """
        获取当前会话的有效条目（按优先级升序）
        不活跃的会被直接移除
        """
        entries = self._data.get(umo)
        if not entries:
            return []

        # 只保留活跃的
        active_entries = [e for e in entries if e.active]

        if not active_entries:
            self._data.pop(umo, None)
            return []

        # priority 数字越小，顺序越靠前
        active_entries.sort(key=lambda x: x.priority)

        # 回写：确保 data 里只有活跃的
        self._data[umo] = active_entries
        return active_entries

    def attach(self, umo: str, entries: list[LoreEntry]) -> None:
        """
        将条目挂载到会话中

        - 条目同名则覆盖（新 > 旧）
        - allow_same_priority=False ：最终不允许同 priority 并存（新 > 旧）
        - allow_same_priority=True ：允许同 priority 并存
        """

        # 1. 取出旧条目
        old_entries = self.get_sorted_active(umo)

        # 2. 深拷贝新条目
        new_entries: list[LoreEntry] = [copy.deepcopy(e) for e in entries]

        # 3. 按 name 合并（新覆盖旧）
        old_by_name: dict[str, LoreEntry] = {e.name: e for e in old_entries}
        new_by_name: dict[str, LoreEntry] = {e.name: e for e in new_entries}

        merged_by_name: dict[str, LoreEntry] = dict(old_by_name)
        merged_by_name.update(new_by_name)  # 新 > 旧

        merged: list[LoreEntry] = list(merged_by_name.values())

        # 4. 按 priority 合并（可选）
        if not self.cfg.allow_same_priority:
            by_priority: dict[int, LoreEntry] = {}

            # 关键点：
            # merged 中已经保证「同名新 > 旧」
            # 这里再次利用 dict 覆盖，保证「同 priority 新 > 旧」
            for e in merged:
                if e.priority in by_priority:
                    logger.debug(
                        f"优先级[{e.priority}]冲突，已覆盖条目: "
                        f"{by_priority[e.priority].name} -> {e.name}"
                    )
                by_priority[e.priority] = e

            merged = list(by_priority.values())

        # 挂载条目到会话下
        self._data[umo] = merged

        # 激活最终条目
        for e in merged:
            e.enter_session()

        logger.debug(f"已挂载并激活条目: {[e.name for e in merged]}")

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
            logger.debug(f"Removed {removed} from {umo}")
        else:
            self._data.pop(umo, None)
            logger.debug(f"Removed all entries from {umo}")

        return removed

    def clear(self, umo: str) -> None:
        """
        强制清除会话的所有prompts
        """
        self._data.pop(umo, None)
        logger.debug(f"[SessionManager] clear session {umo}")
