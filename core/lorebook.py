# core/entry.py
from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

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
        self.entries: list[LoreEntry] = []
        self.on_changed: list[Callable[[], None]] = []

    async def initialize(self):
        self._register_entry()
        asyncio.create_task(asyncio.to_thread(self._load_lorefiles))
        self._save_config()
        logger.debug(f"已注册条目: {'、'.join(p.name for p in self.entries)}")

    def _register_entry(self) -> None:
        """注册配置中的所有条目（兜底保证 name 唯一）"""
        for item in self.cfg.entry_storage:
            raw_name = item.get("name")
            if not raw_name:
                continue

            unique_name = self._resolve_unique_name(raw_name)

            if unique_name != raw_name:
                logger.warning(
                    f"[lorebook] 检测到重复条目名，已重命名: {raw_name} -> {unique_name}"
                )
                item["name"] = unique_name

            self.entries.append(LoreEntry(item))

    def _load_lorefiles(self) -> None:
        """依次加载 cfg.lorefiles 中的路径"""
        for file in self.cfg.lorefiles:
            try:
                self.load_entry_from_lorefile(file)
            except Exception as e:
                logger.error(f"[entry] load failed: {file} ({e})")

    def _sort_entries_by_priority(self) -> None:
        """原地排序 entries（地址不变）"""
        self.entries.sort(key=lambda e: e.priority)
        cfg_map = {cfg["name"]: cfg for cfg in self.cfg.entry_storage}
        self.cfg.entry_storage[:] = [cfg_map[e.name] for e in self.entries]

    def _save_config(self) -> None:
        """
        保存配置前统一兜底：
        - 按 priority 排序
        - 同步 entries / entry_storage 顺序
        """
        self._sort_entries_by_priority()
        self.cfg.save_config()

    def _emit_changed(self):
        for cb in self.on_changed:
            cb()

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
        """获取全部启用的条目"""
        return [entry for entry in self.entries if entry.enabled]

    def list_disabled_entries(self) -> list[LoreEntry]:
        """获取当前已禁用的条目"""
        return [e for e in self.entries if not e.enabled]

    def list_entries_sorted(self) -> list[LoreEntry]:
        """获取按 priority 排序的全部 entries"""
        return sorted(self.entries, key=lambda p: p.priority)

    # ================= CRUD 接口 =================

    def _resolve_unique_name(self, name: str) -> str:
        """
        生成不重名的条目名，采用 name_2 / name_3 / ... 形式
        """
        if not self.get_entry(name):
            return name

        index = 2
        while True:
            new_name = f"{name}_{index}"
            if not self.get_entry(new_name):
                return new_name
            index += 1

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

    def add_entry(
        self,
        data: dict | None = None,
        *,
        name: str | None = None,
        content: str | None = None,
    ) -> LoreEntry:
        """
        新增一个条目

        必填：
            - name
            - content
        其余字段根据 template / 默认规则自动补全
        """
        if data is None:
            data = {}

        # ===== 参数合并（命令 / 代码调用优先）=====
        if name is not None:
            data["name"] = name.strip()
        if content is not None:
            data["content"] = content.strip()

        if not data.get("name"):
            raise ValueError("add_entry 缺少必填字段: name")
        if not data.get("content"):
            raise ValueError("add_entry 缺少必填字段: content")

        # ===== 获取唯一名称 =====
        entry_name = self._resolve_unique_name(data["name"])

        # ===== 模板解析 =====
        template = Template.from_data(data)
        defaults = template.defaults()

        # ===== 字段统一解析 =====
        enabled = self._resolve(data, defaults, "enabled", fallback=True)
        scope = self._resolve(data, defaults, "scope", fallback=[])
        keywords = self._resolve(data, defaults, "keywords", fallback=[])
        cron = self._resolve(data, defaults, "cron", fallback="")
        duration = self._resolve(data, defaults, "duration", fallback=0)
        times = self._resolve(data, defaults, "times", fallback=0)
        probability = self._resolve(data, defaults, "probability", fallback=1.0)
        # priority 单独处理
        priority = self._resolve_priority(data, defaults)

        # ===== 组装最终 entry 数据 =====
        full_data = {
            "__template_key": template.value,
            "template": template.value,
            "name": entry_name,
            "enabled": enabled,
            "priority": priority,
            "scope": scope,
            "keywords": keywords,
            "cron": cron,
            "duration": duration,
            "times": times,
            "probability": probability,
            "content": data["content"],
        }

        # ===== 创建并注册 =====
        entry = LoreEntry(full_data)
        self.entries.append(entry)
        self.cfg.entry_storage.append(full_data)
        self._save_config()
        if entry.enabled_cron:
            self._emit_changed()
        logger.info(
            f"新增条目: {entry.name} "
            f"(template={template.value}, priority={entry.priority})"
        )
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

        self.entries[:] = remaining_entries
        self.cfg.entry_storage[:] = remaining_configs
        if success:
            self._save_config()
            self._emit_changed()

        return success, failed

    # ================= 配置接口 =================

    def add_scope_to_entry(self, name: str, scope: str) -> bool:
        e = self.get_entry(name)
        if not e:
            return False
        changed = e.add_scope(scope)
        if changed:
            self._save_config()
        return True

    def remove_scope_from_entry(self, name: str, scope: str) -> bool:
        entry = self.get_entry(name)
        if not entry:
            return False
        changed = entry.remove_scope(scope)
        if changed:
            self._save_config()
        return True

    def update_keywords(self, name: str, keywords: list[str]) -> bool:
        entry = self.get_entry(name)
        if not entry:
            return False

        entry.set_keywords(keywords)
        self._save_config()
        return True

    def update_priority(self, name: str, priority: int) -> bool:
        entry = self.get_entry(name)
        if not entry:
            return False

        entry.set_priority(priority)
        self._save_config()
        return True

    # ================= 读取文件 =================

    def load_entry_from_lorefile(self, path: str, skip_same: bool = True) -> None:
        """
        从世界书文件中加载条目到配置中
        规则:
          - 仅支持 Json 和 Yaml 文件
          - 同名条目会跳过
        """
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
                skipped_names.append(name or "unknown")
                continue

            if self.get_entry(name) and skip_same:
                skipped += 1
                skipped_names.append(name)
                continue

            try:
                self.add_entry(item)
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
