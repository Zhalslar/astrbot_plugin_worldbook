from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from astrbot.api import logger

from .entry import LoreEntry


class LoreFile:
    """
    世界书文件协议层

    职责：
    - 文件 <-> 原始 entry dict
    - JSON / YAML 支持
    - 结构兼容与兜底
    """

    # === 对外接口 ===

    @staticmethod
    def load(path: Path) -> list[dict[str, Any]]:
        """
        从 lorefile 中读取原始 entry dict 列表
        """
        if not path.exists():
            raise FileNotFoundError(path)

        data = LoreFile._load_raw(path)

        # 兼容：
        # - list[dict]
        # - { entries: [...] }
        if isinstance(data, dict) and "entries" in data:
            data = data["entries"]

        if not isinstance(data, list):
            raise ValueError(
                f"文件格式错误: {path}，必须是 list[dict] 或 {{entries: [...]}}"
            )

        entries: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                logger.warning(f"[lorefile] 跳过非法项: {item}")
                continue
            entries.append(item)

        return entries

    @staticmethod
    def dump(entries: list[LoreEntry]) -> list[dict[str, Any]]:
        """
        LoreEntry -> 可序列化 dict（不包含运行时状态）
        """
        result: list[dict[str, Any]] = []
        for e in entries:
            result.append(LoreFile._entry_to_dict(e))
        return result

    @staticmethod
    def save(path: Path, entries: list[LoreEntry]) -> None:
        """
        将 LoreEntry 列表写入 lorefile
        """
        payload = {
            "entries": LoreFile.dump(entries),
        }

        suffix = path.suffix.lower()
        try:
            if suffix in {".yaml", ".yml"}:
                with path.open("w", encoding="utf-8") as f:
                    yaml.safe_dump(
                        payload,
                        f,
                        allow_unicode=True,
                        sort_keys=False,
                    )
                return

            if suffix == ".json":
                with path.open("w", encoding="utf-8") as f:
                    json.dump(
                        payload,
                        f,
                        ensure_ascii=False,
                        indent=2,
                    )
                return

            raise ValueError(f"不支持的文件类型: {suffix}")

        except Exception as e:
            raise RuntimeError(f"写入 lorefile 失败: {e}") from e

    # === 内部工具 ===

    @staticmethod
    def _load_raw(path: Path) -> Any:
        suffix = path.suffix.lower()
        try:
            with path.open("r", encoding="utf-8") as f:
                if suffix in {".yaml", ".yml"}:
                    import yaml

                    return yaml.safe_load(f)

                if suffix == ".json":
                    import json

                    return json.load(f)

                raise ValueError(f"不支持的文件类型: {suffix}")
        except Exception as e:
            raise RuntimeError(f"读取 lorefile 失败: {e}") from e

    @staticmethod
    def _entry_to_dict(entry: LoreEntry) -> dict[str, Any]:
        """
        LoreEntry -> 标准 lorefile dict（规范协议）
        """
        return {
            "template": entry.template.value,
            "name": entry.name,
            "enabled": entry.enabled,
            "priority": entry.priority,
            "scope": list(entry.scope),
            "keywords": list(entry.keywords),
            "probability": entry.probability,
            "content": entry.content,
            "duration": entry.duration,
            "times": entry.times,
        }
