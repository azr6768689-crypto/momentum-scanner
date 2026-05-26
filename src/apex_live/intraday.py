"""Intraday bars and session statistics (Polygon minute bars)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntradayStats:
    symbol: str
    last: float
    open: float
    high: float
    low: float
    volume: float
    pct_change: float
    rvol_vs_avg: float
    vwap: float
    dist_vwap_pct: float
    bars: int


def _empty_stats(symbol: str) -> IntradayStats:
    return IntradayStats(
        symbol=symbol,
        last=0.0,
        open=0.0,
        high=0.0,
        low=0.0,
        volume=0.0,
        pct_change=0.0,
        rvol_vs_avg=0.0,
        vwap=0.0,
        dist_vwap_pct=0.0,
        bars=0,
    )


def stats_from_minute_df(symbol: str, df: pd.DataFrame, avg_daily_volume: float = 0.0) -> IntradayStats:
    if df is None or df.empty:
        return _empty_stats(symbol)
    work = df.sort_index()
    last = float(work["close"].iloc[-1])
    open_ = float(work["open"].iloc[0])
    high = float(work["high"].max())
    low = float(work["low"].min())
    vol = float(work["volume"].sum())
    typical = (work["high"] + work["low"] + work["close"]) / 3.0
    vwap = float((typical * work["volume"]).sum() / max(vol, 1.0))
    pct = (last / open_ - 1.0) * 100.0 if open_ > 0 else 0.0
    dist_vwap = (last / vwap - 1.0) * 100.0 if vwap > 0 else 0.0
    # Rough intraday RVOL: today volume vs 1/6 of 20d avg (6.5h session)
    expected_session = max(avg_daily_volume / 6.5, 1.0) if avg_daily_volume > 0 else max(vol, 1.0)
    rvol = vol / expected_session
    return IntradayStats(
        symbol=symbol,
        last=last,
        open=open_,
        high=high,
        low=low,
        volume=vol,
        pct_change=pct,
        rvol_vs_avg=rvol,
        vwap=vwap,
        dist_vwap_pct=dist_vwap,
        bars=len(work),
    )


def fetch_intraday_stats(
    provider: Any,
    symbol: str,
    *,
    avg_daily_volume: float = 0.0,
    multiplier: int = 5,
    timespan: str = "minute",
) -> IntradayStats:
    """Load today's session bars and compute live stats."""
    sym = symbol.upper().strip()
    end = date.today()
    start = end - timedelta(days=3)

    try:
        if hasattr(provider, "get_minute_bars"):
            df = provider.get_minute_bars(sym, start, end, multiplier=multiplier, timespan=timespan)
        elif hasattr(provider, "get_intraday_bars"):
            df = provider.get_intraday_bars(sym, start, end)
        else:
            return _empty_stats(sym)
    except Exception as exc:
        log.warning("Intraday fetch failed for %s: %s", sym, exc)
        return _empty_stats(sym)

    if df.empty:
        return _empty_stats(sym)

    try:
        from src.apex_live.session import now_ny

        today = pd.Timestamp(now_ny().date())
        session = df[df.index >= today]
        if not session.empty:
            df = session
    except Exception:
        df = df.tail(80)

    return stats_from_minute_df(sym, df, avg_daily_volume=avg_daily_volume)
