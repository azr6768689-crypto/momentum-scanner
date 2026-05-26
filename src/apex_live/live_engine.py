"""Live watchlist scanner — intraday refresh loop."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.apex_live.alerts import AlertEngine, AlertEvent
from src.apex_live.intraday import IntradayStats, fetch_intraday_stats

log = logging.getLogger(__name__)


@dataclass
class LiveSnapshot:
    symbol: str
    last: float
    pct_day: float
    rvol: float
    vwap: float
    dist_vwap_pct: float
    high: float
    volume: float
    apex_score: float | None
    rs_rating: float | None
    setup: str
    trigger: float | None
    bars: int

    def to_row(self) -> dict[str, Any]:
        return {
            "סימבול": self.symbol,
            "מחיר": round(self.last, 2),
            "שינוי יום %": round(self.pct_day, 2),
            "RVOL יומי": round(self.rvol, 2),
            "VWAP": round(self.vwap, 2),
            "מעל VWAP %": round(self.dist_vwap_pct, 2),
            "שיא יום": round(self.high, 2),
            "ווליום": int(self.volume),
            "Apex": "" if self.apex_score is None else int(self.apex_score),
            "RS": "" if self.rs_rating is None else int(self.rs_rating),
            "דפוס": self.setup,
            "טריגר": "" if self.trigger is None else round(self.trigger, 2),
            "bars": self.bars,
        }


def _merge_daily_context(
    symbol: str,
    daily_report: pd.DataFrame | None,
) -> tuple[float | None, float | None, str, float | None]:
    if daily_report is None or daily_report.empty or "סימבול" not in daily_report.columns:
        return None, None, "", None
    row = daily_report[daily_report["סימבול"].astype(str).str.upper() == symbol.upper()]
    if row.empty:
        return None, None, "", None
    r = row.iloc[0]
    apex = pd.to_numeric(r.get("Apex Score"), errors="coerce")
    rs = pd.to_numeric(r.get("RS Rating"), errors="coerce")
    setup = str(r.get("דפוס", "") or "")
    trig = pd.to_numeric(r.get("כניסה"), errors="coerce")
    return (
        float(apex) if pd.notna(apex) else None,
        float(rs) if pd.notna(rs) else None,
        setup,
        float(trig) if pd.notna(trig) else None,
    )


def _scan_one(
    symbol: str,
    provider: Any,
    daily_report: pd.DataFrame | None,
) -> tuple[LiveSnapshot | None, list[AlertEvent]]:
    sym = symbol.upper().strip()
    apex, rs, setup, trigger = _merge_daily_context(sym, daily_report)
    stats: IntradayStats = fetch_intraday_stats(provider, sym)
    if stats.bars == 0 and stats.last <= 0:
        return None, []

    snap = LiveSnapshot(
        symbol=sym,
        last=stats.last,
        pct_day=stats.pct_change,
        rvol=stats.rvol_vs_avg,
        vwap=stats.vwap,
        dist_vwap_pct=stats.dist_vwap_pct,
        high=stats.high,
        volume=stats.volume,
        apex_score=apex,
        rs_rating=rs,
        setup=setup,
        trigger=trigger,
        bars=stats.bars,
    )
    engine = AlertEngine()
    events = engine.evaluate_symbol(
        sym,
        last=stats.last,
        pct_day=stats.pct_change,
        rvol=stats.rvol_vs_avg,
        high_of_day=stats.high,
        apex_score=apex,
        trigger_price=trigger,
    )
    return snap, events


def scan_live_watchlist(
    symbols: list[str],
    provider: Any,
    daily_report: pd.DataFrame | None = None,
    *,
    workers: int = 6,
) -> tuple[list[LiveSnapshot], list[AlertEvent]]:
    symbols = [s.upper().strip() for s in symbols if str(s).strip()]
    if not symbols:
        return [], []

    snapshots: list[LiveSnapshot] = []
    all_events: list[AlertEvent] = []
    workers = max(1, min(workers, 12, len(symbols)))

    if len(symbols) > 3 and workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_scan_one, s, provider, daily_report): s for s in symbols}
            for fut in as_completed(futs):
                snap, ev = fut.result()
                if snap:
                    snapshots.append(snap)
                all_events.extend(ev)
    else:
        for s in symbols:
            snap, ev = _scan_one(s, provider, daily_report)
            if snap:
                snapshots.append(snap)
            all_events.extend(ev)

    snapshots.sort(key=lambda x: (x.pct_day, x.rvol), reverse=True)
    if all_events:
        AlertEngine().merge_events(all_events)
    return snapshots, all_events
