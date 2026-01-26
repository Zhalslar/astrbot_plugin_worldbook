# core/entry.py
from __future__ import annotations

import random
import re
import time

from astrbot.api import logger

from .config import ConfigNode
from .template import Template


class LoreEntry(ConfigNode):
    """
    LoreEntry 是【激活决策的唯一权威】。

    激活模型（务必遵守）：
    ==================================================
    【激活资格（OR）】
      - keywords 命中
      - cron 已触发（运行期状态）

    【激活门禁（AND，按顺序）】
      1. enabled        ：总开关
      2. scope          ：权限大门（越早越好）
      3. 激活资格       ：是否被“点名”
      4. duration       ：时间是否过期
      5. times          ：次数是否耗尽
      6. probability    ：随机（必须最后）

    ⚠️ 任何地方都【不得】绕过 can_activate 做判断
    ==================================================
    """

    __template_key: str | None

    # ===== 配置字段 =====
    name: str
    enabled: bool
    priority: int
    scope: list[str]
    keywords: list[str]
    probability: float
    cron: str
    content: str
    duration: int
    times: int

    # ===== 运行期字段（不持久化）=====
    _activated_at: float | None  # 实际进入 session 的时间
    _inject_count: int  # 已注入次数
    _cron_triggered: bool  # 是否被 cron 触发过（激活资格）
    _compiled_patterns: list[re.Pattern]

    def __init__(self, data: dict):
        super().__init__(data)

        self._template = Template.from_data(data)

        # 运行期状态初始化
        self._activated_at = None
        self._inject_count = 0

        # cron 触发标记：
        # - 只表示“获得一次激活资格”
        # - 不代表已经激活
        self._cron_triggered = False

        # 编译关键词
        self._compiled_patterns = []
        self._compile_patterns()

    # ==================================================
    # 基础状态
    # ==================================================

    @property
    def template(self) -> Template:
        return self._template

    @property
    def activated(self) -> bool:
        """是否已经进入激活态（已写入 session）"""
        return self._activated_at is not None

    # ---------------- 时间 / 次数 ----------------

    @property
    def expired(self) -> bool:
        """
        是否因 duration 过期
        """
        if self._activated_at is None:
            return False

        if self.duration == 0:  # 0 表示永久
            return False

        return time.time() >= self._activated_at + self.duration

    @property
    def remaining(self) -> int:
        """剩余生效时间（秒）"""
        if self.duration == 0:
            return 0

        if self._activated_at is None:
            return self.duration

        return max(0, int(self.duration - (time.time() - self._activated_at)))

    # ==================================================
    # 激活资格（keywords / cron）
    # ==================================================

    def _compile_patterns(self) -> None:
        """
        编译关键词正则
        """
        self._compiled_patterns.clear()

        # 没有关键词时，默认用 name
        self.keywords = [k for k in self.keywords if k.strip()] or [self.name]

        for pattern in self.keywords:
            try:
                self._compiled_patterns.append(re.compile(pattern))
            except re.error as e:
                logger.warning(f"[条目:{self.name}] 正则编译失败: {pattern} ({e})")

    def match(self, text: str) -> bool:
        """是否命中关键词"""
        return any(p.search(text) for p in self._compiled_patterns)

    def has_activation_token(self, text: str | None) -> bool:
        """
        是否具备“激活资格”

        这是【事件相关判断】：
        - keywords：消息事件
        - cron：时间事件
        """
        if text and self.match(text):
            return True

        if self._cron_triggered:
            return True

        return False

    # ==================================================
    # Scope / Probability：激活门禁
    # ==================================================

    def allow_scope(
        self,
        *,
        user_id: str | None = None,
        group_id: str | None = None,
        session_id: str | None = None,
        is_admin: bool = False,
    ) -> bool:
        """
        scope 判定（权限大门）

        这是【硬性权限】，应尽早失败
        """
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
        """
        概率判定

        ⚠️ 必须是最后一步：
        - 不可复现
        - 会消耗随机
        """
        p = self.probability

        if p >= 1.0:
            return True
        if p <= 0.0:
            return False

        return random.random() < p

    # ==================================================
    # 核心：统一激活决策（唯一入口）
    # ==================================================

    def can_activate(
        self,
        *,
        text: str | None,
        user_id: str | None,
        group_id: str | None,
        session_id: str | None,
        is_admin: bool,
    ) -> bool:
        """
        判断在给定上下文下，是否可以激活该 LoreEntry

        决策顺序（推荐 & 已验证合理）：
        ------------------------------------------------
        1. enabled        ：总开关
        2. scope          ：权限（尽早失败）
        3. 激活资格       ：keywords / cron
        4. duration       ：是否过期
        5. times          ：次数是否耗尽
        6. probability    ：随机（最后）
        ------------------------------------------------
        """

        # 1. 总开关
        if not self.enabled:
            return False

        # 2. 权限大门
        if not self.allow_scope(
            user_id=user_id,
            group_id=group_id,
            session_id=session_id,
            is_admin=is_admin,
        ):
            return False

        # 3. 是否被“点名”（事件相关）
        if not self.has_activation_token(text):
            return False

        # 4. duration（时间）
        if self.expired:
            return False

        # 5. times（次数）
        if self.times > 0 and self._inject_count >= self.times:
            return False

        # 6. probability（随机，必须最后）
        if not self.allow_probability():
            return False

        return True

    # ==================================================
    # 生命周期钩子
    # ==================================================

    def on_cron_triggered(self) -> None:
        """
        被 cron 触发，获得一次激活资格
        """
        self._cron_triggered = True

    def on_activated(self) -> None:
        """
        成功激活后调用

        说明：
        - cron 提供的是“一次性激活资格”
        - 真正激活后必须清除
        """
        self._cron_triggered = False

    # ==================================================
    # 配置修改接口
    # ==================================================

    def set_keywords(self, keywords: list[str]) -> None:
        self.keywords = keywords or []
        self._compile_patterns()

    def set_priority(self, priority: int) -> None:
        self.priority = priority

    def add_scope(self, scope: str) -> bool:
        if scope in self.scope:
            return False
        self.scope.append(scope)
        return True

    def remove_scope(self, scope: str) -> bool:
        if scope not in self.scope:
            return False

        self.scope.remove(scope)

        # 避免 scope 变成“全开”
        if not self.scope:
            self.scope.append("admin")

        return True

    # ==================================================
    # 展示
    # ==================================================

    def display(self) -> str:
        """以 Markdown 表格（两行）形式展示条目配置"""

        # ===== 状态 =====
        status_text = "启用" if self.enabled else "禁用"

        # ===== 激活条件（资格来源）=====
        conditions = []
        if self.keywords:
            conditions.append("关键词")
        if self.cron:
            conditions.append("定时")
        condition_text = " / ".join(conditions) if conditions else "无"

        # ===== 激活范围（scope）=====
        if not self.scope:
            scope_text = "所有会话"
        elif self.scope == ["admin"]:
            scope_text = "仅管理员"
        else:
            scope_text = ", ".join("管理员" if s == "admin" else s for s in self.scope)

        # ===== 生命周期 =====
        duration_text = "永久" if self.duration == 0 else f"{self.duration} 秒"
        times_text = "不限次数" if self.times == 0 else f"{self.times} 次"
        probability_text = f"{int(self.probability * 100)}%"

        # ===== 关键词（单独展示）=====
        if self.keywords:
            keywords_text = " | ".join(self.keywords)
        else:
            keywords_text = f"（默认：{self.name}）"

        lines = [
            f"### 【{self.name}】",
            "",
            "| 状态 | 优先级 | 激活条件 | 激活范围 | 注入时长 | 注入次数 | 激活概率 |",
            "| ---- | ------ | -------- | -------- | -------- | -------- | -------- |",
            f"| {status_text} | {self.priority} | {condition_text} | {scope_text} | {duration_text} | {times_text} | {probability_text} |",
            "",
            "- 触发关键词",
            f"  {keywords_text}",
            "",
            "```",
            self.content,
            "```",
        ]

        return "\n".join(lines)
