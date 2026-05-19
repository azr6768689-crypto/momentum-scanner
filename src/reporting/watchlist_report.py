"""
Watchlist CSV generator.

The Watchlist is for setups in the score band [watchlist_score, main_report_score).
These are interesting but NOT ready — they require confirmation.

The CSV is structurally identical to the main report so it can be loaded
the same way in the dashboard. The difference:
- Every row is marked Confidence Level: WATCH ONLY
- An explicit "Needs Confirmation" column makes the not-ready status obvious
- A "Watchlist Reason" column explains why this is a watchlist (not main)

Critical: every row must include the full trade plan: entry_trigger,
stop_loss, target_1, target_2, risk_reward, invalidation, what_to_wait_for.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from src.scoring.score_engine import ScoredSignal
from src.analytics.indicators import IndicatorSnapshot


CONFIDENCE_WATCH_ONLY = "WATCH ONLY / LOWER CONFIDENCE / NEEDS CONFIRMATION"

WATCHLIST_COLUMNS = [
    "Rank", "Ticker", "Confidence Level", "Watchlist Reason",
    "Needs Confirmation", "Current Price", "Setup Type", "Scanner Mode",
    "Strategy Module", "Score", "Score Band", "Status", "% Change Today",
    "Volume", "Avg Volume 20d", "RVOL", "Dollar Volume 20d", "Trend",
    "Price vs SMA20", "Price vs SMA50", "Dist from SMA20 %",
    "Dist from SMA50 %", "ATR Extension", "ATR(14)", "20d High",
    "50d High", "52w High", "entry_trigger", "stop_loss", "target_1",
    "target_2", "risk_reward", "invalidation", "what_to_wait_for",
    "breakout_level", "distance_to_breakout_pct", "Reason", "Warnings",
    "Liquidity Score", "Liquidity Warnings",
]


def generate_watchlist_csv(
    scored_signals: list[ScoredSignal],
    snapshots: dict[str, IndicatorSnapshot],
    output_dir: Path,
    main_score_threshold: int,
    run_date: date | None = None,
    filename_format: str = "{date}_watchlist.csv",
    liquidity_results: dict | None = None,
) -> Path:
    """Write the daily watchlist CSV.

    Returns the path to the created file.
    """
    run_date = run_date or date.today()
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = filename_format.format(date=run_date.isoformat())
    filepath = output_dir / filename
    liquidity_results = liquidity_results or {}

    rows: list[dict[str, Any]] = []

    for rank, scored in enumerate(scored_signals, start=1):
        sig = scored.signal
        snap = snapshots.get(sig.ticker)
        if snap is None:
            continue

        # What's the reason this is a watchlist item, not main?
        watchlist_reason = _build_watchlist_reason(scored, sig, main_score_threshold)
        breakout_level, distance_to_breakout_pct = _breakout_fields(sig, snap)

        row: dict[str, Any] = {
            "Rank": rank,
            "Ticker": sig.ticker,
            "Confidence Level": CONFIDENCE_WATCH_ONLY,
            "Watchlist Reason": watchlist_reason,
            "Needs Confirmation": "YES — not trade-ready",
            "Current Price": round(snap.close, 2),
            "Setup Type": sig.setup_type,
            "Scanner Mode": sig.scanner_mode,
            "Strategy Module": sig.strategy_module,
            "Score": scored.final_score,
            "Score Band": scored.score_band,
            "Status": sig.status,
            "% Change Today": round(snap.pct_change_1d, 2),
            "Volume": int(snap.volume),
            "Avg Volume 20d": int(snap.avg_volume_20),
            "RVOL": round(snap.rvol_20, 2),
            "Dollar Volume 20d": int(snap.dollar_volume_20),
            "Trend": snap.trend,
            "Price vs SMA20": f"{'above' if snap.close > snap.sma20 else 'below'} (${snap.sma20:.2f})",
            "Price vs SMA50": f"{'above' if snap.close > snap.sma50 else 'below'} (${snap.sma50:.2f})",
            "Dist from SMA20 %": round(snap.dist_from_sma20_pct, 2),
            "Dist from SMA50 %": round(snap.dist_from_sma50_pct, 2),
            "ATR Extension": round(snap.atr_ext_above_sma20, 2),
            "ATR(14)": round(snap.atr14, 2),
            "20d High": round(snap.high_20d, 2),
            "50d High": round(snap.high_50d, 2),
            "52w High": round(snap.high_52w, 2) if snap.high_52w else "N/A",
            # The 7 trade-plan fields the user explicitly requires
            "entry_trigger": round(sig.entry_trigger, 2),
            "stop_loss":     round(sig.stop_loss, 2),
            "target_1":      round(sig.target_1, 2),
            "target_2":      round(sig.target_2, 2),
            "risk_reward":   round(sig.risk_reward, 2),
            "invalidation":  sig.invalidation,
            "what_to_wait_for": sig.wait_for,
            "breakout_level": breakout_level,
            "distance_to_breakout_pct": distance_to_breakout_pct,
            # Narrative
            "Reason": sig.reason,
            "Warnings": "; ".join(sig.warnings) if sig.warnings else "",
        }

        # Liquidity
        liq = liquidity_results.get(sig.ticker)
        if liq:
            row["Liquidity Score"] = liq.liquidity_score
            row["Liquidity Warnings"] = "; ".join(liq.warnings) if liq.warnings else ""
        else:
            row["Liquidity Score"] = ""
            row["Liquidity Warnings"] = ""

        rows.append(row)

    df = pd.DataFrame(rows, columns=WATCHLIST_COLUMNS)
    df.to_csv(filepath, index=False, encoding="utf-8")
    return filepath


def _build_watchlist_reason(scored: ScoredSignal, sig, main_threshold: int) -> str:
    """Explain why this candidate is on the WATCHLIST and not the Main Report.

    The most common cause is "score below main threshold". We add specifics
    where we can read them off the signal/status.
    """
    parts: list[str] = []
    parts.append(f"Score {scored.final_score} < main threshold {main_threshold}")

    if sig.status == "Watch":
        parts.append("setup pending — entry trigger not hit yet")
    elif sig.status == "Wait for pullback":
        parts.append("price is extended — waiting for pullback")
    elif sig.status == "Trigger":
        parts.append("triggered but composite score below main threshold")

    if sig.warnings:
        # Surface the most relevant warning
        parts.append(sig.warnings[0])

    return "; ".join(parts)


def _breakout_fields(sig, snap) -> tuple[float | str, float | str]:
    """Return breakout level and positive distance-to-breakout for near-trigger rows."""
    breakout_level = sig.factor_inputs.get("prior_high") or sig.factor_inputs.get("breakout_level")
    if not breakout_level or snap is None or snap.close <= 0:
        return "", ""

    level = float(breakout_level)
    distance = (level / snap.close - 1.0) * 100.0
    return round(level, 2), round(distance, 2)
