"""US market session helpers."""

from __future__ import annotations

from datetime import datetime, time

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore


NY = ZoneInfo("America/New_York") if ZoneInfo else None


def now_ny() -> datetime:
    if NY:
        return datetime.now(NY)
    return datetime.now()


def is_us_market_open() -> bool:
    """Regular session Mon–Fri 9:30–16:00 ET (no holidays)."""
    now = now_ny()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return time(9, 30) <= t <= time(16, 0)


def session_label() -> str:
    if is_us_market_open():
        return "שוק פתוח (RTH)"
    now = now_ny()
    if now.weekday() >= 5:
        return "סוף שבוע"
    t = now.time()
    if t < time(9, 30):
        return "לפני פתיחה"
    return "אחרי סגירה"
