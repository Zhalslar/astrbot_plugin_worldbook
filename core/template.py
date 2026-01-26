from __future__ import annotations

from enum import Enum
from typing import Any


class Template(str, Enum):
    DEFAULT = "default"
    RESIDENT = "resident"
    CHANCE = "chance"
    USER = "user"
    GROUP = "group"

    @classmethod
    def values(cls) -> set[str]:
        return {e.value for e in cls}

    @property
    def is_default(self) -> bool:
        return self is Template.DEFAULT

    @property
    def is_resident(self) -> bool:
        return self is Template.RESIDENT

    @property
    def is_random(self) -> bool:
        return self is Template.CHANCE

    @property
    def is_user(self) -> bool:
        return self is Template.USER

    @property
    def is_group(self) -> bool:
        return self is Template.GROUP

    @classmethod
    def from_data(cls, data: dict) -> "Template":  # noqa: UP037
        """
        从配置数据中解析 template 类型
        - 优先读取新字段 template
        - 兼容旧字段 __template_key
        - 不存在时使用默认值
        - 非法值直接抛 ValueError
        """
        raw = data.get("template") or data.get("__template_key") or cls.DEFAULT.value

        try:
            return cls(raw)
        except ValueError:
            raise ValueError(
                f"未知的模板类型 template={raw}，可选值: {', '.join(cls.values())}"
            )

    def defaults(self) -> dict[str, Any]:
        """
        返回该模板下的字段默认值

        规则：
        - default 模板定义基准值
        - 其他模板只覆盖差异字段
        """
        base = {
            "priority": 50,
            "keywords": [],
            "duration": 180,
            "times": 5,
        }

        overrides: dict[Template, dict[str, Any]] = {
            Template.RESIDENT: {
                "priority": 20,
                "keywords": [".*"],
                "duration": 0,
                "times": 0,
            },
            Template.CHANCE: {
                "priority": 1,
                "keywords": [".*"],
                "times": 1,
            },
            Template.USER: {
                "priority": 120,
                "keywords": [".*"],
                "duration": 0,
                "times": 0,
            },
            Template.GROUP: {
                "priority": 110,
                "keywords": [".*"],
                "duration": 0,
                "times": 0,
            },
        }

        result = dict(base)
        result.update(overrides.get(self, {}))
        return result
