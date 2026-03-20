# core/scheduler.py
from __future__ import annotations

from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from astrbot.api import logger

if TYPE_CHECKING:
    from .entry import LoreEntry
    from .lorebook import Lorebook
    from .session import SessionCache


def _normalize_weekday_field(field: str) -> str:
    """
    Convert standard crontab weekdays (0/7=Sun, 1=Mon, ..., 6=Sat)
    to APScheduler weekdays (0=Mon, ..., 6=Sun).
    """

    def normalize_token(token: str) -> str:
        token = token.strip().lower()
        if not token:
            return token
        if token in {"*", "sun", "mon", "tue", "wed", "thu", "fri", "sat"}:
            return token
        if token.isdigit():
            value = int(token)
            if not 0 <= value <= 7:
                raise ValueError(f"invalid weekday: {token}")
            return "6" if value in {0, 7} else str(value - 1)
        raise ValueError(f"invalid weekday: {token}")

    def normalize_part(part: str) -> str:
        base, *step = part.split("/", maxsplit=1)
        if "-" in base:
            start, end = base.split("-", maxsplit=1)
            base = f"{normalize_token(start)}-{normalize_token(end)}"
        else:
            base = normalize_token(base)

        if not step:
            return base
        return f"{base}/{step[0].strip()}"

    return ",".join(normalize_part(part) for part in field.split(","))


def _build_trigger(cron_expr: str) -> CronTrigger:
    minute, hour, day, month, weekday = cron_expr.split()
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=_normalize_weekday_field(weekday),
    )


class LoreCronScheduler:
    """
    LoreEntry 定时激活调度器（cron → 触发条目）
    """

    def __init__(self, lorebook: Lorebook, sessions: SessionCache):
        # 只依赖两个“纯业务对象”，不依赖 plugin / event
        self._lorebook = lorebook
        self._sessions = sessions

        # APScheduler 本体
        self._scheduler = AsyncIOScheduler()
        self._started = False

        # 订阅 Lorebook 的变更事件
        self._lorebook.on_changed.append(self.reload)

    # ========== 生命周期 ==========

    def start(self) -> None:
        """
        启动调度器：
        - 注册所有合法 cron
        - 启动 AsyncIOScheduler

        只允许启动一次
        """
        if self._started:
            return

        self._register_all()
        self._scheduler.start()
        self._started = True
        logger.debug("[cron] scheduler started")

    def shutdown(self) -> None:
        """
        停止调度器（插件卸载 / 进程退出时调用）
        """
        if not self._started:
            return

        self._scheduler.shutdown(wait=False)
        self._started = False
        logger.debug("[cron] scheduler stopped")

    def reload(self) -> None:
        """
        重新加载所有 cron 任务

        使用场景：
        - 新增 / 删除条目
        - 修改条目的 cron 字段
        """
        if not self._started:
            return

        self._scheduler.remove_all_jobs()
        self._register_all()
        logger.debug("[cron] scheduler reloaded")

    # ========== 内部实现 ==========

    def _register_all(self) -> None:
        """
        遍历所有 entry，尝试注册其 cron
        """
        for entry in self._lorebook.list_entries():
            if entry.enabled_cron:
                self._try_register_entry(entry)

    def _try_register_entry(self, entry: LoreEntry) -> None:
        """
        尝试为单个 entry 注册 cron 任务
        """
        try:
            # 使用标准 5 段 cron：分 时 日 月 周
            trigger = _build_trigger(entry.cron)
        except Exception as e:
            logger.warning(
                f"[cron] 条目 {entry.name} cron 无效，已忽略: {entry.cron} ({e})"
            )
            return

        # job_id 使用 entry.name，确保 reload / 覆盖是幂等的
        job_id = f"loreentry:{entry.name}"

        self._scheduler.add_job(
            self._on_trigger,
            trigger=trigger,
            args=[entry.name],
            id=job_id,
            replace_existing=True,
        )

        logger.debug(f"[cron] 已注册定时条目: {entry.name} ({entry.cron})")

    def _on_trigger(self, entry_name: str) -> None:
        entry = self._lorebook.get_entry(entry_name)
        if not entry or not entry.enabled:
            return

        # 只通知 entry：cron 已触发
        entry.on_cron_triggered()
