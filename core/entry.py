# core/entry.py
from __future__ import annotations

import random
import re
import time
from typing import Any

from astrbot.api import logger

from .config import ConfigNode
from .template import Template


class LoreEntry(ConfigNode):
    """
    LoreEntry 模型: 描述一个世界书的条目。
    """

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

    def __init__(self, data: dict):
        super().__init__(data)
        # 模板
        self._template = Template.from_data(data)

        # 本条目的激活时间，也是条目进入激发态的标志
        self._activated_at = None

        # 注入次数, 大于等于 times 时本条目生效周期结束
        self._inject_count = 0

        # cron 触发时间
        self._cron_fired_at: float | None = None

        # 编译并缓存正则
        self._compiled_patterns: list[re.Pattern] = []
        self._compile_patterns()

    @property
    def template(self) -> Template:
        return self._template

    def to_dict(self) -> dict[str, Any]:
        """
        LoreEntry -> lorefile dict
        """
        return {
            "template": self.template.value,
            "name": self.name,
            "enabled": self.enabled,
            "priority": self.priority,
            "scope": list(self.scope),
            "keywords": list(self.keywords),
            "probability": self.probability,
            "cron": self.cron,
            "content": self.content,
            "duration": self.duration,
            "times": self.times,
        }

    # ==================================================
    # 编译正则
    # ==================================================

    def _compile_patterns(self) -> None:
        """编译正则"""
        self._compiled_patterns.clear()
        self.keywords = [k for k in self.keywords if k.strip()]

        for pattern in self.keywords:
            try:
                self._compiled_patterns.append(re.compile(pattern))
            except re.error as e:
                logger.warning(f"[条目:{self.name}] 正则编译失败: {pattern} ({e})")

    def _match_keywords(self, text: str) -> bool:
        """是否命中任一关键词正则"""
        for p in self._compiled_patterns:
            if p.search(text):
                logger.debug(f"[条目:{self.name}] 命中正则: {p.pattern}")
                return True
        return False

    # ==================================================
    # 基础状态
    # ==================================================

    @property
    def active(self) -> bool:
        """条目是否正处于激活态"""
        if self._activated_at is None:
            return False

        now = time.time()

        # 判断是否过期
        if self.duration > 0 and now > self._activated_at + self.duration:
            logger.debug(f"[条目:{self.name}]  已过期")
            return False

        # 判断是否耗尽次数
        if self.times > 0 and self._inject_count >= self.times:
            logger.debug(
                f"[条目:{self.name}]  已耗尽次数({self._inject_count}/{self.times})"
            )
            return False

        return True

    @property
    def remaining_time(self) -> float:
        """剩余有效时间（秒）"""
        if self._activated_at is None:
            return 0

        # 永久有效
        if self.duration <= 0:
            return float("inf")

        now = time.time()
        end_time = self._activated_at + self.duration
        return max(0, end_time - now)

    @property
    def remaining_times(self) -> int | float:
        """剩余可用次数"""
        if self._activated_at is None:
            return 0

        # 次数无限
        if self.times <= 0:
            return float("inf")

        return max(0, self.times - self._inject_count)

    @property
    def enabled_keywords(self) -> bool:
        if not self._compiled_patterns:
            return False
        return True

    @property
    def enabled_cron(self) -> bool:
        """是否启用定时任务 (标准 5 段 cron)"""
        if not self.enabled:
            return False
        return len(str(self.cron).split()) == 5

    @property
    def in_cron_window(self) -> bool:
        """
        是否处于 cron 激活窗口内
        """
        if not self.enabled_cron:
            return False
        if self._cron_fired_at is None:
            return False

        # duration <= 0 表示永久窗口
        if self.duration <= 0:
            return True

        return time.time() <= self._cron_fired_at + self.duration

    # ==================================================
    # 激活决策
    # ==================================================

    def _allow_scope(
        self,
        *,
        user_id: str | None,
        group_id: str | None,
        session_id: str | None,
        is_admin: bool,
    ) -> bool:
        """scope 权限大门 (尽早失败)"""
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

    def _has_text_token(self, text: str | None) -> bool:
        """是否具备文本激活资格"""
        if not text:
            return False
        if not self.enabled_keywords:
            return False
        return self._match_keywords(text)

    def _satisfy_probability(self) -> bool:
        """概率是否满足"""
        p = self.probability
        if p >= 1.0:
            return True
        if p <= 0.0:
            return False
        prob = random.random()
        if prob < p:
            logger.debug(f"[{self.name}] 概率激活成功: {prob} < {p}")
            return True
        return False

    def check_activate(
        self,
        *,
        text: str | None,
        user_id: str | None,
        group_id: str | None,
        session_id: str | None,
        is_admin: bool,
    ) -> bool:
        """
        统一激活判决, 在监听LLM消息时调用
        """

        # Gate 1: 总开关
        if not self.enabled:
            return False

        # Gate 2: scope 权限大门
        if not self._allow_scope(
            user_id=user_id,
            group_id=group_id,
            session_id=session_id,
            is_admin=is_admin,
        ):
            return False

        # Gate 3: 激活方式（满足其一即可）
        if not self._has_text_token(text) and not self.in_cron_window:
            return False

        # Gate 4: 激活的概率
        if not self._satisfy_probability():
            return False

        return True

    # ==================================================
    # 生命周期钩子
    # ==================================================

    def enter_session(self) -> None:
        """
        进入会话的唯一入口（激活发生点）
        """
        # 记录激活时间, 进入触发态
        self._activated_at = time.time()

    def on_consume(self) -> None:
        """
        记录一次使用（注入消耗）

        说明:
        - 每次注入 system_prompt 后调用
        - 仅影响运行期次数统计
        """
        self._inject_count += 1

    def on_cron_triggered(self) -> None:
        """
        被 cron 触发，打开一次全局激活窗口
        """
        self._cron_fired_at = time.time()
        logger.debug(f"[cron] 条目 {self.name} cron 已触发，等待消息激活")

    # ==================================================
    # 展示
    # ==================================================

    @staticmethod
    def format_duration(seconds: float) -> str:
        if seconds <= 0:
            return "0秒"

        seconds = int(seconds)

        # 10 分钟以内，直接用秒
        if seconds <= 600:
            return f"{seconds}秒"

        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)

        if days > 0:
            return f"{days}天{hours}小时" if hours else f"{days}天"
        if hours > 0:
            return f"{hours}小时{minutes}分" if minutes else f"{hours}小时"
        return f"{minutes}分"

    def display(self) -> str:
        """以 Markdown 表格形式展示条目配置与运行状态"""

        # ===== 基础状态 =====
        if not self.enabled:
            status_text = "禁用"
        elif self.active:
            status_text = "生效中"
        else:
            status_text = "待触发"

        # ===== 激活范围（scope）=====
        if not self.scope:
            scope_text = "所有会话"
        elif self.scope == ["admin"]:
            scope_text = "仅管理员"
        else:
            scope_text = ", ".join("管理员" if s == "admin" else s for s in self.scope)

        # ===== 生命周期 =====
        if self.duration == 0:
            duration_text = "永久"
        elif self.active:
            duration_text = f"剩余 {self.format_duration(self.duration)} 秒"
        else:
            duration_text = f"{self.duration} 秒"

        times_text = "不限次数" if self.times == 0 else f"{self.times} 次"
        probability_text = f"{int(self.probability * 100)}%"

        lines = [f"### 【{self.name}】"]

        # ===== 触发关键词（有就展示）=====
        if self.keywords:
            keywords_text = "  |  ".join(self.keywords)
            lines.append(f"- 正则触发:  {keywords_text}")

        # ===== 定时规则（有就展示）=====
        if self.cron:
            lines.append(f"- 定时触发:  {self.cron}")

        lines.extend(
            [
                "| 状态 | 优先级 | 激活范围 | 生效时长 | 生效次数 | 生效概率 |",
                "| ---- | ------ | -------- | -------- | -------- | -------- |",
                f"| {status_text} | {self.priority} | {scope_text} | {duration_text} | {times_text} | {probability_text} |",
            ]
        )
        # ===== 内容 =====
        lines.extend(
            [
                "```",
                self.content.strip(),
                "```",
            ]
        )

        return "\n".join(lines)

    def display_remaining(self):
        """显示条目当前剩余时间和次数"""
        parts = []

        if self.duration > 0:
            parts.append(f"剩{self.format_duration(self.remaining_time)}")
        else:
            parts.append("∞")

        if self.times > 0:
            parts.append(f"{self.remaining_times}次")
        else:
            parts.append("∞")

        return f"{self.name}({'、'.join(parts)})" if parts else self.name
