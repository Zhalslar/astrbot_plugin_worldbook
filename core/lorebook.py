# core/entry.py
from __future__ import annotations

import asyncio
from pathlib import Path

from astrbot.api import logger

from .config import PluginConfig
from .entry import LoreEntry
from .lorefile import LoreFile


class Lorebook:
    """
    世界书核心业务层
    """

    def __init__(self, config: PluginConfig):
        self.cfg = config
        self.entries: list[LoreEntry] = []

    async def initialize(self):
        self._register_entry()
        self._refresh_enabled_cache()
        asyncio.create_task(asyncio.to_thread(self._load_lorefiles))
        self.cfg.save_config()
        logger.debug(f"已注册条目: {'、'.join(p.name for p in self.entries)}")

    def _register_entry(self) -> None:
        """注册配置中的所有条目"""
        for item in self.cfg.entry_storage:
            entry = LoreEntry(item)
            self.entries.append(entry)

    def _load_lorefiles(self) -> None:
        """依次加载 cfg.lorefiles 中的路径"""
        for file in self.cfg.lorefiles:
            try:
                self.load_entry_from_lorefile(file, override=False)
            except Exception as e:
                logger.error(f"[entry] load failed: {file} ({e})")

    def _refresh_enabled_cache(self) -> None:
        """刷新启用条目缓存（内部使用）"""
        self._enabled_entries_cache: list[LoreEntry] = [
            e for e in self.entries if e.enabled
        ]

    def _next_priority(self, avoid_admin: bool = True) -> int:
        """获取下一个可用的 priority"""

        if not self.entries:
            priority = 0
        else:
            priority = max(p.priority for p in self.entries) + 1

        if not avoid_admin:
            return priority

        return priority

    # ================= 查询接口 =================

    def get_entry(self, name: str) -> LoreEntry | None:
        """按 name 获取单个条目"""
        for entry in self.entries:
            if entry.name == name:
                return entry
        return None

    def list_entries(self) -> list[LoreEntry]:
        """获取全部条目（包含启用和禁用）"""
        return list(self.entries)

    def list_enabled_entries(self) -> list[LoreEntry]:
        """获取当前已启用的条目"""
        return list(self._enabled_entries_cache)

    def list_disabled_entries(self) -> list[LoreEntry]:
        """获取当前已禁用的条目"""
        return [e for e in self.entries if not e.enabled]

    def list_entries_sorted(self) -> list[LoreEntry]:
        """获取按 priority 排序的全部 entries"""
        return sorted(self.entries, key=lambda p: p.priority)

    # ================= CRUD 接口 =================

    def add_entry(
        self,
        data: dict | None = None,
        *,
        name: str | None = None,
        content: str | None = None,
        override: bool = False,
    ) -> LoreEntry:
        """
        新增一个条目

        必填：
            - name: str
            - content: str
        其余字段自动补全
        """
        if data is None:
            data = {}

        if name is not None:
            data["name"] = name
        if content is not None:
            data["content"] = content

        if not data.get("name"):
            raise ValueError("add_entry 缺少必填字段: name")
        if not data.get("content"):
            raise ValueError("add_entry 缺少必填字段: content")

        entry_name = data["name"]
        existing = self.get_entry(entry_name)
        if existing:
            if not override:
                raise ValueError(f"Prompt 已存在: {entry_name}")
            self.remove_entries([entry_name])

        full_data = {
            "__template_key": data.get("__template_key", "default"),
            "name": data["name"],
            "enabled": data.get("enabled", True),
            "priority": data.get("priority", self._next_priority()),
            "scope": data.get("scope", []),
            "keywords": data.get("keywords", []),
            "content": data["content"],
            "duration": data.get("duration", self.cfg.default_duration),
            "times": data.get("times", self.cfg.default_times),
        }

        entry = LoreEntry(full_data)
        self.entries.append(entry)
        self.cfg.entry_storage.append(full_data)

        self._refresh_enabled_cache()
        self.cfg.save_config()

        logger.info(f"新增 entry: {entry.name} (priority={entry.priority})")
        return entry

    def remove_entries(self, names: list[str]) -> tuple[list[str], list[str]]:
        """按 name 批量删除条目"""
        success: list[str] = []
        failed: list[str] = []

        remaining_entries: list[LoreEntry] = []
        remaining_configs: list[dict] = []

        for entry, cfg in zip(self.entries, self.cfg.entry_storage):
            if entry.name in names:
                success.append(entry.name)
            else:
                remaining_entries.append(entry)
                remaining_configs.append(cfg)

        for name in names:
            if name not in success:
                failed.append(name)

        self.entries = remaining_entries
        self.cfg.entry_storage = remaining_configs

        self._refresh_enabled_cache()
        self.cfg.save_config()
        return success, failed

    # ================= 配置接口 =================

    def add_scope_to_entry(self, name: str, scope: str) -> bool:
        e = self.get_entry(name)
        if not e:
            return False
        changed = e.add_scope(scope)
        if changed:
            self.cfg.save_config()
        return True

    def remove_scope_from_entry(self, name: str, scope: str) -> bool:
        entry = self.get_entry(name)
        if not entry:
            return False
        changed = entry.remove_scope(scope)
        if changed:
            self.cfg.save_config()
        return True

    def update_keywords(self, name: str, keywords: list[str]) -> bool:
        entry = self.get_entry(name)
        if not entry:
            return False

        entry.set_keywords(keywords)
        self.cfg.save_config()
        return True

    def update_priority(self, name: str, priority: int) -> bool:
        entry = self.get_entry(name)
        if not entry:
            return False

        entry.set_priority(priority)
        self._refresh_enabled_cache()
        self.cfg.save_config()
        return True

    # ================= 运行时匹配接口 =================

    @property
    def enabled_entries(self) -> list[LoreEntry]:
        """获取启用条目（原始顺序）"""
        return self._enabled_entries_cache

    def enabled_sorted_entries(self) -> list[LoreEntry]:
        """获取按 priority 排序后的启用条目"""
        return sorted(
            self._enabled_entries_cache,
            key=lambda p: p.priority,
        )

    def match_entries(self, text: str) -> list[LoreEntry]:
        matched: list[LoreEntry] = []
        for entry in self.enabled_sorted_entries():
            if entry.available and entry.match(text):
                matched.append(entry)
        return matched

    # ================= 读取文件 =================

    def load_entry_from_lorefile(
        self,
        path: str,
        *,
        override: bool = False,
    ) -> None:
        file_path = Path(path)

        try:
            raw_entries = LoreFile.load(file_path)
        except Exception as e:
            logger.error(f"[lorebook] 加载失败: {file_path} ({e})")
            return

        total = 0
        loaded = 0
        skipped = 0
        failed = 0

        skipped_names: list[str] = []
        failed_items: list[tuple[str, str]] = []

        for item in raw_entries:
            total += 1
            name = item.get("name")
            content = item.get("content")

            if not name or not content:
                skipped += 1
                skipped_names.append(name or "<unknown>")
                continue

            existing = self.get_entry(name)
            if existing and not override:
                skipped += 1
                skipped_names.append(name)
                continue

            try:
                self.add_entry(item, override=override)
                loaded += 1
            except Exception as e:
                failed += 1
                failed_items.append((name, str(e)))

        # ===== 汇总日志（只打一条 info）=====
        logger.info(
            f"[lorebook] 加载完成: 总数={total}, 成功={loaded}, 跳过={skipped}, 失败={failed}"
        )

        # ===== 详细信息仅在 debug 级别 =====
        if skipped_names:
            logger.debug(f"[lorebook] 跳过的条目: {', '.join(skipped_names)}")

        if failed_items:
            for name, err in failed_items:
                logger.debug(f"[lorebook] 条目加载失败: {name} ({err})")

    def export_lorefile(self, path: str) -> None:
        """
        导出当前世界书为 lorefile（用于分享）
        """
        file_path = Path(path)
        try:
            LoreFile.save(file_path, self.entries)
            logger.info(f"[lorebook] 世界书已导出: {file_path}")
        except Exception as e:
            logger.error(f"[lorebook] 导出失败: {file_path} ({e})")
