# core/entry.py
from __future__ import annotations

import random
import re
import time

from astrbot.api import logger

from .config import ConfigNode


class LoreEntry(ConfigNode):
    __template_key: str
    name: str
    enabled: bool
    priority: int
    scope: list[str]
    keywords: list[str]
    probability: float
    content: str
    duration: int
    times: int

    def __init__(self, data: dict):
        super().__init__(data)

        self._activated_at: float | None = None
        self._inject_count: int = 0
        self._compiled_patterns: list[re.Pattern] = []
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        self._compiled_patterns.clear()
        self.keywords = [r for r in self.keywords if r.strip()] or [self.name]
        for pattern in self.keywords:
            try:
                self._compiled_patterns.append(re.compile(pattern))
            except re.error as e:
                logger.warning(f"[条目:{self.name}] 正则编译失败: {pattern} ({e})")

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

    def match(self, text: str) -> bool:
        return any(pattern.search(text) for pattern in self._compiled_patterns)

    def add_scope(self, scope: str) -> bool:
        # True 表示有变更
        if scope in self.scope:
            return False
        self.scope.append(scope)
        return True

    def remove_scope(self, scope: str) -> bool:
        if scope not in self.scope:
            return False

        self.scope.remove(scope)

        # 关键：避免 scope 变成“全开”
        if not self.scope:
            self.scope.append("admin")

        return True

    def allow_scope(
        self,
        *,
        user_id: str | None = None,
        group_id: str | None = None,
        session_id: str | None = None,
        is_admin: bool = False,
    ) -> bool:
        # 留空：所有会话均可触发
        if not self.scope:
            return True

        for s in self.scope:
            if s == "admin" and is_admin:
                return True
            if user_id and s == user_id:
                return True
            if group_id and s == group_id:
                return True
            if session_id and s == session_id:
                return True

        return False

    def allow_probability(self) -> bool:
        p = self.probability
        if p >= 1.0:
            return True
        if p <= 0.0:
            return False
        return random.random() < p

    def set_keywords(self, keywords: list[str]) -> None:
        self.keywords = keywords or []
        self._compile_patterns()

    def set_priority(self, priority: int) -> None:
        self.priority = priority

    def display(self) -> str:
        """以可读文本形式展示该提示词"""

        status = "启用" if self.enabled else "禁用"
        priority = self.priority

        # 触发词
        if self.keywords:
            keywords_text = " | ".join(self.keywords)
        else:
            keywords_text = f"（默认匹配词： {self.name}）"

        # 会话范围
        if not self.scope:
            scope_text = "所有会话"
        elif self.scope == ["admin"]:
            scope_text = "仅管理员"
        else:
            display_scope = []
            for s in self.scope:
                if s == "admin":
                    display_scope.append("管理员")
                else:
                    display_scope.append(s)
            scope_text = ", ".join(display_scope)

        # 注入限制
        duration_text = "永久" if self.duration == 0 else f"{self.duration} 秒"
        times_text = "不限次数" if self.times == 0 else f"{self.times} 次"

        lines = [
            f"### 【{self.name}】",
            f"- 状态：{status}",
            f"- 优先级：{priority}",
            f"- 触发词：{keywords_text}",
            f"- 触发会话：{scope_text}",
            f"- 注入时长：{duration_text}",
            f"- 注入次数：{times_text}",
            "",
            "```",
            self.content,
            "```",
        ]

        return "\n".join(lines)
