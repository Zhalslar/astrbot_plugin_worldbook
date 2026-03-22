# core/entry.py
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from astrbot.api import logger

from .config import PluginConfig
from .entry import LoreEntry, Template
from .lorefile import LoreFile


class Lorebook:
    """
    世界书核心业务层
    """

    def __init__(self, config: PluginConfig):
        self.cfg = config
        self.entry_map: dict[str, LoreEntry] = {}
        self.on_changed: list[Callable[[], None]] = []

    @property
    def entries(self) -> list[LoreEntry]:
        return list(self.entry_map.values())

    async def initialize(self):
        if self.cfg.entry_storage:
            names = self._register_entry(self.cfg.entry_storage)
        else:
            logger.debug("[lorebook] 未配置 entry_storage, 将使用默认配置")
            names = self.load_entry_from_lorefile(self.cfg.default_lorefile)
        logger.debug(f"已注册条目: {names}")

    def _register_entry(
        self, items: list[dict[str, Any]], skip_same: bool = True,
    ) -> list[str]:
        """注册条目（兜底保证 name 唯一）"""
        registered_names: list[str] = []
        for item in items:
            name = item.get("name")
            content = item.get("content")
            if not name or not content:
                continue
            if skip_same and name in self.entry_map:
                logger.warning(f"[lorebook] 已存在同名条目: {name}")
                continue
            entry = LoreEntry(item)
            self.entry_map[name] = entry
            registered_names.append(entry.name)
            if item not in self.cfg.entry_storage:
                self.cfg.entry_storage.append(item)
            if entry.enabled_cron:
                self._emit_changed()

        self._save_config()
        return registered_names

    def _save_config(self) -> None:
        """
        保存配置前统一兜底：
        - 按 priority 排序
        - 同步 entries / entry_storage 顺序
        """
        cfg_map = {cfg["name"]: cfg for cfg in self.cfg.entry_storage}
        sorted_entries = sorted(self.entry_map.values(), key=lambda e: e.priority)
        self.cfg.entry_storage[:] = [cfg_map[e.name] for e in sorted_entries]
        self.cfg.save_config()

    def _emit_changed(self):
        for cb in self.on_changed:
            cb()

    # ================= 查询接口 =================

    def get_entry(self, name: str) -> LoreEntry | None:
        """按 name 获取单个条目"""
        return self.entry_map.get(name)

    def list_entries(self) -> list[LoreEntry]:
        """获取全部条目（包含启用和禁用）"""
        return list(self.entry_map.values())

    def list_enabled_entries(self) -> list[LoreEntry]:
        """获取全部启用的条目"""
        return [entry for entry in self.entries if entry.enabled]

    def list_disabled_entries(self) -> list[LoreEntry]:
        """获取当前已禁用的条目"""
        return [e for e in self.entries if not e.enabled]

    def list_entries_sorted(self) -> list[LoreEntry]:
        """获取按 priority 排序的全部 entries"""
        return sorted(self.entries, key=lambda p: p.priority)

    # ================= CRUD 接口 =================

    def _resolve(
        self,
        data: dict,
        defaults: dict,
        key: str,
        *,
        fallback,
    ):
        """
        通用字段解析：
        用户指定 > 模板默认 > fallback
        """
        if key in data:
            return data[key]
        if key in defaults:
            return defaults[key]
        return fallback

    def _resolve_priority(
        self,
        data: dict,
        defaults: dict,
        *,
        key: str = "priority",
    ) -> int:
        """
        priority 规则：
        - 用户显式指定：直接使用
        - 否则：从模板默认 priority（base）开始，取第一个 > base 的可用自增优先级
        """
        # 1. 用户指定（最高优先级）
        if key in data:
            return data[key]

        # 2. 模板起始 priority（base）
        base = defaults.get(key, 0)

        # 3. 收集所有已占用的 priority
        used = {e.priority for e in self.entries}

        # 4. 从 base + 1 开始，找第一个未被占用的
        p = base + 1
        while p in used:
            p += 1

        return p

    def add_entries(
        self,
        items: list[dict[str, Any]] | None = None,
        *,
        name: str | None = None,
        content: str | None = None,
    ) -> list[str]:
        """
        新增一个条目

        必填：
            - name
            - content
        其余字段根据 template / 默认规则自动补全
        """
        if items is None:
            items = []

        if name is not None and content is not None:
            items.append({"name": name, "content": content})

        if not items:
            raise ValueError("add_entries 缺少参数")

        full_items = []
        for item in items:
            # ===== 模板解析 =====
            template = Template.from_data(item)
            defaults = template.defaults()

            # ===== 字段统一解析 =====
            enabled = self._resolve(item, defaults, "enabled", fallback=True)
            scope = self._resolve(item, defaults, "scope", fallback=[])
            keywords = self._resolve(item, defaults, "keywords", fallback=[])
            cron = self._resolve(item, defaults, "cron", fallback="")
            duration = self._resolve(item, defaults, "duration", fallback=0)
            times = self._resolve(item, defaults, "times", fallback=0)
            probability = self._resolve(item, defaults, "probability", fallback=1.0)
            # priority 单独处理
            priority = self._resolve_priority(item, defaults)

            # ===== 组装最终 entry 数据 =====
            full_item = {
                "__template_key": template.value,
                "template": template.value,
                "name": item["name"],
                "enabled": enabled,
                "priority": priority,
                "scope": scope,
                "keywords": keywords,
                "cron": cron,
                "duration": duration,
                "times": times,
                "probability": probability,
                "content": item["content"],
            }
            full_items.append(full_item)

        registered_names = self._register_entry(full_items)
        return registered_names

    def remove_entries(self, names: list[str]) -> tuple[list[str], list[str]]:
        """按 name 批量删除条目"""
        success: list[str] = []
        failed: list[str] = []
        removed_names: set[str] = set()

        for name in names:
            if self.entry_map.pop(name, None) is not None:
                success.append(name)
                removed_names.add(name)
            else:
                failed.append(name)

        if removed_names:
            self.cfg.entry_storage[:] = [
                cfg
                for cfg in self.cfg.entry_storage
                if cfg.get("name") not in removed_names
            ]
        if success:
            self._save_config()
            self._emit_changed()

        return success, failed

    # ================= 配置接口 =================

    def add_scope_to_entry(self, name: str, scope: str) -> bool:
        e = self.entry_map.get(name)
        if not e:
            return False
        changed = e.add_scope(scope)
        if changed:
            self._save_config()
        return True

    def remove_scope_from_entry(self, name: str, scope: str) -> bool:
        entry = self.entry_map.get(name)
        if not entry:
            return False
        changed = entry.remove_scope(scope)
        if changed:
            self._save_config()
        return True

    def update_keywords(self, name: str, keywords: list[str]) -> bool:
        entry = self.entry_map.get(name)
        if not entry:
            return False

        entry.set_keywords(keywords)
        self._save_config()
        return True

    def update_priority(self, name: str, priority: int) -> bool:
        entry = self.entry_map.get(name)
        if not entry:
            return False

        entry.set_priority(priority)
        self._save_config()
        return True

    # ================= 读取文件 =================

    def load_entry_from_lorefile(self, file_path: Path) -> None:
        """
        从世界书文件中加载条目到配置中
        规则:
          - 仅支持 Json 和 Yaml 文件
          - 同名条目会跳过
        """
        try:
            raw_entries = LoreFile.load(file_path)
            self.add_entries(raw_entries)
        except Exception as e:
            logger.error(f"[lorebook] 加载失败: {file_path} ({e})")
            return

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
