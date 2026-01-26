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


class LoreCronScheduler:
    """
    LoreEntry 定时激活调度器（cron → 会话激活）

    设计说明（非常重要）：
    ------------------------------------------------
    1. cron 是一种「主动激活源」
       - 不依赖用户消息
       - 不依赖现有 SessionCache 状态

    2. entry.scope 的语义：
       - scope 中的每一个元素，都被视为一个 session_id（umo）
       - cron 触发时，scope 即为“激活目标列表”

    4. 本调度器职责：
       - 到点 → 对 entry.scope 中的每个 umo 调用 SessionCache.activate

    规则：
    - cron 为空 / 非法：忽略
    - 使用 5 段 cron（分 时 日 月 周）
    - 激活逻辑复用 SessionCache.activate
    """

    def __init__(self, lorebook: Lorebook, sessions: SessionCache):
        # 只依赖两个“纯业务对象”，不依赖 plugin / event
        self._lorebook = lorebook
        self._sessions = sessions

        # APScheduler 本体
        self._scheduler = AsyncIOScheduler()
        self._started = False

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
        - 导入世界书
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
            self._try_register_entry(entry)

    def _try_register_entry(self, entry: LoreEntry) -> None:
        """
        尝试为单个 entry 注册 cron 任务

        注意：
        - cron 为空：视为未启用
        - cron 非法：记录 warning，但不中断系统
        """
        cron = (entry.cron or "").strip()
        if not cron:
            return

        try:
            # 使用标准 5 段 cron：分 时 日 月 周
            trigger = CronTrigger.from_crontab(cron)
        except Exception as e:
            logger.warning(f"[cron] 条目 {entry.name} cron 无效，已忽略: {cron} ({e})")
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

        logger.info(f"[cron] 注册条目: {entry.name} ({cron})")

    def _on_trigger(self, entry_name: str) -> None:
        entry = self._lorebook.get_entry(entry_name)
        if not entry or not entry.enabled:
            return

        # 只通知 entry：cron 已触发
        entry.on_cron_triggered()

        logger.debug(f"[cron] 条目 {entry.name} cron 已触发，等待消息激活")
