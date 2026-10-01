# core/holidays.py
"""
中国法定节假日 / 调休工作日判定

数据来自 NateScarlet/holiday-cn 的 CDN（与国务院放假安排同步），
拉取后缓存到插件数据目录，由后台线程负责补齐与刷新，
判定函数本身完全离线、可同步调用。

判断优先级：
1. holiday-cn 缓存数据（包含调休）
2. 仅按周一~周五判断（缓存缺失时的保底）
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from datetime import date
from pathlib import Path

from astrbot.api import logger
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

CDN_BASE = "https://fastly.jsdelivr.net/gh/NateScarlet/holiday-cn@master"
PLUGIN_NAME = "astrbot_plugin_worldbook"

# 缓存文件超过 30 天就重新拉取一次，
# 这样当年补发的调休调整和次年放假安排都能跟上
CACHE_TTL_SECONDS = 30 * 24 * 3600
FETCH_TIMEOUT = 8


class HolidayCalendar:
    """
    节假日数据管理器（线程安全）
    """

    def __init__(self) -> None:
        self._dir = Path(get_astrbot_plugin_data_path()) / PLUGIN_NAME / "holidays"
        self._dir.mkdir(parents=True, exist_ok=True)

        # year -> (休息日集合, 调休补班日集合)
        self._years: dict[int, tuple[frozenset[date], frozenset[date]]] = {}
        self._lock = threading.Lock()
        self._inflight: set[int] = set()

    # ---------- 缓存读写 ----------

    def _cache_path(self, year: int) -> Path:
        return self._dir / f"{year}.json"

    def _load_cache(self, year: int) -> tuple[frozenset[date], frozenset[date]] | None:
        path = self._cache_path(year)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        days = data.get("days")
        if not isinstance(days, list):
            return None

        off: set[date] = set()
        makeup: set[date] = set()
        for item in days:
            try:
                d = date.fromisoformat(item["date"])
            except (TypeError, ValueError):
                continue
            (off if item.get("isOffDay") else makeup).add(d)
        return frozenset(off), frozenset(makeup)

    def _save_cache(self, year: int, raw: str) -> None:
        try:
            self._cache_path(year).write_text(raw, encoding="utf-8")
            logger.info(f"[holiday] 已缓存 {year} 年节假日数据")
        except OSError as e:
            logger.warning(f"[holiday] 缓存 {year} 年数据失败: {e}")

    # ---------- 后台拉取 ----------

    def _need_refresh(self, year: int) -> bool:
        path = self._cache_path(year)
        if not path.exists():
            return True
        try:
            return time.time() - path.stat().st_mtime > CACHE_TTL_SECONDS
        except OSError:
            return True

    def _fetch_year(self, year: int) -> None:
        url = f"{CDN_BASE}/{year}.json"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "astrbot"})
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8")
            parsed = json.loads(raw)
            if not isinstance(parsed, dict) or not isinstance(parsed.get("days"), list):
                raise ValueError("数据格式异常")
        except Exception as e:
            logger.warning(f"[holiday] 拉取 {year} 年数据失败: {e}")
            return

        self._save_cache(year, raw)
        loaded = self._load_cache(year)
        if loaded is not None:
            with self._lock:
                self._years[year] = loaded

    def _ensure_year(self, year: int) -> None:
        """确保某年份的数据被加载；缺失或过期时交给后台线程异步刷新"""
        if year not in self._years:
            loaded = self._load_cache(year)
            if loaded is not None:
                self._years[year] = loaded

        if not self._need_refresh(year):
            return

        with self._lock:
            if year in self._inflight:
                return
            self._inflight.add(year)

        def worker() -> None:
            try:
                self._fetch_year(year)
            finally:
                with self._lock:
                    self._inflight.discard(year)

        threading.Thread(target=worker, daemon=True).start()

    # ---------- 对外判定 ----------

    def is_workday(self, today: date) -> bool:
        """
        判断某天是否为中国法定工作日（含调休补班）
        """
        self._ensure_year(today.year)

        data = self._years.get(today.year)
        if data is not None:
            off, makeup = data
            if today in off:
                return False
            if today in makeup:
                return True

        # 缓存缺失时保底：仅按周末判断
        return today.weekday() < 5

    def match_filter(self, filter_mode: str, today: date) -> bool:
        """
        判断某天是否满足节假日过滤
        - workday:  仅工作日通过（法定节假日与周末跳过，调休上班的周末照常）
        - holiday:  仅节假日/周末通过（调休上班的周末跳过）
        - 其他:     始终通过
        """
        if filter_mode not in {"workday", "holiday"}:
            return True
        is_workday = self.is_workday(today)
        return is_workday if filter_mode == "workday" else not is_workday


_default_calendar: HolidayCalendar | None = None


def get_calendar() -> HolidayCalendar:
    global _default_calendar
    if _default_calendar is None:
        _default_calendar = HolidayCalendar()
    return _default_calendar
