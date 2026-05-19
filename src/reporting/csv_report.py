"""
CSV report writer.

Exports all scored signals to a CSV file with every column the user specified.
One CSV per daily run, saved to data/reports/YYYY-MM-DD_report.csv.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from src.scoring.score_engine import ScoredSignal
from src.analytics.indicators import IndicatorSnapshot
from src.analytics.market_regime import MarketRegime


REPORT_COLUMNS = [
    "Rank", "Ticker", "Symbol", "Last Close", "Percent Change", "Relative Volume",
    "Trend Status", "Breakout Status", "Setup Probability %", "Score", "Category", "Reason Plain English",
    "Suggested Trigger", "Invalidation/Stop Area", "Risk Note",
    "Current Price", "Setup Type", "Scanner Mode",
    "Strategy Module", "Score Band", "Status", "% Change Today",
    "Volume", "Avg Volume 20d", "RVOL", "Dollar Volume 20d", "Trend",
    "Price vs SMA20", "Price vs SMA50", "Dist from SMA20 %",
    "Dist from SMA50 %", "ATR Extension", "ATR(14)", "20d High",
    "50d High", "52w High", "Breakout Dist 20d %",
    "Breakout Dist 50d %", "Entry Trigger", "Stop Loss", "Target 1",
    "Target 2", "Risk/Reward", "entry_trigger", "stop_loss", "target_1",
    "target_2", "risk_reward", "invalidation", "what_to_wait_for",
    "Reason", "Invalidation", "Wait For", "Warnings", "Liquidity Score",
    "Liquidity Warnings",
]

REJECTED_COLUMNS = [
    "Rank", "Ticker", "Score", "Score Band", "Primary Rejection Reason",
    "Setup Type", "Scanner Mode", "Strategy Module", "Status",
    "Current Price", "% Change Today", "RVOL", "Trend",
    "Dist from SMA20 %", "ATR Extension", "Entry Trigger", "Stop Loss",
    "Target 1", "Risk/Reward", "entry_trigger", "stop_loss", "target_1",
    "risk_reward", "invalidation", "what_to_wait_for", "breakout_level",
    "distance_to_breakout_pct", "Warnings", "Reason",
]


def generate_csv_report(
    scored_signals: list[ScoredSignal],
    snapshots: dict[str, IndicatorSnapshot],
    regime: MarketRegime,
    output_dir: Path,
    run_date: date | None = None,
    filename_format: str = "{date}_report.csv",
    liquidity_results: dict | None = None,
    scanned_tickers: list[str] | None = None,
    all_scored_signals: list[ScoredSignal] | None = None,
) -> Path:
    """Write the daily CSV report.

    Returns the path to the created file.
    """
    run_date = run_date or date.today()
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = filename_format.format(date=run_date.isoformat())
    filepath = output_dir / filename
    liquidity_results = liquidity_results or {}

    if scanned_tickers is not None:
        rows = _build_ranked_symbol_rows(
            scanned_tickers=scanned_tickers,
            snapshots=snapshots,
            scored_signals=all_scored_signals if all_scored_signals is not None else scored_signals,
            liquidity_results=liquidity_results,
        )
        df = pd.DataFrame(rows, columns=REPORT_COLUMNS)
        df.to_csv(filepath, index=False, encoding="utf-8")
        return filepath

    rows: list[dict[str, Any]] = []

    for rank, scored in enumerate(scored_signals, start=1):
        sig = scored.signal
        snap = snapshots.get(sig.ticker)
        if snap is None:
            continue

        category = _category_for_score(scored.final_score, sig.risk_reward)
        row: dict[str, Any] = {
            "Rank": rank,
            "Ticker": sig.ticker,
            "Symbol": sig.ticker,
            "Last Close": round(snap.close, 2),
            "Percent Change": round(snap.pct_change_1d, 2),
            "Relative Volume": round(snap.rvol_20, 2),
            "Trend Status": snap.trend,
            "Breakout Status": _breakout_status(snap),
            "Category": category,
            "Reason Plain English": sig.reason,
            "Suggested Trigger": round(sig.entry_trigger, 2),
            "Invalidation/Stop Area": sig.invalidation,
            "Risk Note": _risk_note(category, sig.risk_reward, sig.warnings),
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
            "Breakout Dist 20d %": round(snap.breakout_dist_20d_pct, 2),
            "Breakout Dist 50d %": round(snap.breakout_dist_50d_pct, 2),
            "Entry Trigger": round(sig.entry_trigger, 2),
            "Stop Loss": round(sig.stop_loss, 2),
            "Target 1": round(sig.target_1, 2),
            "Target 2": round(sig.target_2, 2),
            "Risk/Reward": round(sig.risk_reward, 2),
            # Explicit trade-plan field names (Group I requirement)
            "entry_trigger": round(sig.entry_trigger, 2),
            "stop_loss":     round(sig.stop_loss, 2),
            "target_1":      round(sig.target_1, 2),
            "target_2":      round(sig.target_2, 2),
            "risk_reward":   round(sig.risk_reward, 2),
            "invalidation":  sig.invalidation,
            "what_to_wait_for": sig.wait_for,
            "Reason": sig.reason,
            "Invalidation": sig.invalidation,
            "Wait For": sig.wait_for,
            "Warnings": "; ".join(sig.warnings) if sig.warnings else "",
        }

        # Liquidity columns (Group G)
        liq = liquidity_results.get(sig.ticker)
        if liq:
            row["Liquidity Score"] = liq.liquidity_score
            row["Liquidity Warnings"] = "; ".join(liq.warnings) if liq.warnings else ""
        else:
            row["Liquidity Score"] = ""
            row["Liquidity Warnings"] = ""

        rows.append(row)

    df = pd.DataFrame(rows, columns=REPORT_COLUMNS)
    df.to_csv(filepath, index=False, encoding="utf-8")
    return filepath


def _build_ranked_symbol_rows(
    scanned_tickers: list[str],
    snapshots: dict[str, IndicatorSnapshot],
    scored_signals: list[ScoredSignal],
    liquidity_results: dict,
) -> list[dict[str, Any]]:
    best_by_ticker: dict[str, ScoredSignal] = {}
    for scored in sorted(scored_signals, key=lambda s: s.final_score, reverse=True):
        best_by_ticker.setdefault(scored.signal.ticker, scored)

    rows: list[dict[str, Any]] = []
    for ticker in scanned_tickers:
        snap = snapshots.get(ticker)
        scored = best_by_ticker.get(ticker)
        rows.append(_ranked_symbol_row(ticker, snap, scored, liquidity_results.get(ticker)))

    rows.sort(key=lambda row: (int(row["Score"]), row["Ticker"]), reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["Rank"] = rank
    return rows


def _ranked_symbol_row(ticker: str, snap: IndicatorSnapshot | None, scored: ScoredSignal | None, liq: Any) -> dict[str, Any]:
    if snap is None:
        return {
            "Rank": 0,
            "Ticker": ticker,
            "Symbol": ticker,
            "Setup Probability %": 0,
            "Score": 0,
            "Category": "Avoid / Rejected",
            "Status": "No data",
            "Trend Status": "no_data",
            "Breakout Status": "No usable data",
            "Reason Plain English": "No usable market data was fetched for this symbol, likely due to provider rate limiting or missing data.",
            "Risk Note": "Do not evaluate until fresh data is available.",
        }

    if scored is not None:
        sig = scored.signal
        score = scored.final_score
        category = _category_for_score(score, sig.risk_reward)
        reason = sig.reason
        trigger = sig.entry_trigger
        stop_area = sig.invalidation
        risk_reward = sig.risk_reward
        setup_type = sig.setup_type
        scanner_mode = sig.scanner_mode
        strategy_module = sig.strategy_module
        status = sig.status
        warnings = sig.warnings
        target_1 = sig.target_1
        target_2 = sig.target_2
        wait_for = sig.wait_for
    else:
        score = _snapshot_score(snap)
        category = _category_for_score(score, None)
        reason = _plain_snapshot_reason(snap)
        trigger = _suggested_trigger(snap)
        stop_area = _suggested_stop_area(snap)
        risk_reward = ""
        setup_type = "Momentum scan"
        scanner_mode = "snapshot"
        strategy_module = "snapshot_ranker"
        status = "Scanned"
        warnings = []
        target_1 = ""
        target_2 = ""
        wait_for = f"Watch for a move above ${trigger:.2f} with expanding volume."

    row = {
        "Rank": 0,
        "Ticker": ticker,
        "Symbol": ticker,
        "Last Close": round(snap.close, 2),
        "Percent Change": round(snap.pct_change_1d, 2),
        "Relative Volume": round(snap.rvol_20, 2),
        "Trend Status": snap.trend,
        "Breakout Status": _breakout_status(snap),
        "Setup Probability %": score,
        "Score": score,
        "Category": category,
        "Reason Plain English": reason,
        "Suggested Trigger": round(float(trigger), 2),
        "Invalidation/Stop Area": stop_area,
        "Risk Note": _risk_note(category, risk_reward, warnings),
        "Current Price": round(snap.close, 2),
        "Setup Type": setup_type,
        "Scanner Mode": scanner_mode,
        "Strategy Module": strategy_module,
        "Score Band": _score_band_for_score(score),
        "Status": status,
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
        "Breakout Dist 20d %": round(snap.breakout_dist_20d_pct, 2),
        "Breakout Dist 50d %": round(snap.breakout_dist_50d_pct, 2),
        "Entry Trigger": round(float(trigger), 2),
        "Stop Loss": round(_numeric_stop(snap), 2),
        "Target 1": round(float(target_1), 2) if target_1 != "" else "",
        "Target 2": round(float(target_2), 2) if target_2 != "" else "",
        "Risk/Reward": risk_reward,
        "entry_trigger": round(float(trigger), 2),
        "stop_loss": round(_numeric_stop(snap), 2),
        "target_1": round(float(target_1), 2) if target_1 != "" else "",
        "target_2": round(float(target_2), 2) if target_2 != "" else "",
        "risk_reward": risk_reward,
        "invalidation": stop_area,
        "what_to_wait_for": wait_for,
        "Reason": reason,
        "Invalidation": stop_area,
        "Wait For": wait_for,
        "Warnings": "; ".join(warnings) if warnings else "",
        "Liquidity Score": getattr(liq, "liquidity_score", "") if liq else "",
        "Liquidity Warnings": "; ".join(getattr(liq, "warnings", []) or []) if liq else "",
    }
    return row


def _snapshot_score(snap: IndicatorSnapshot) -> int:
    score = 0.0
    score += {"uptrend_strong": 35, "uptrend_weak": 24, "sideways": 10, "downtrend": 0}.get(snap.trend, 5)
    score += max(0.0, min(20.0, (snap.rvol_20 - 0.8) / 1.7 * 20.0))
    score += max(0.0, min(15.0, (snap.pct_change_1d + 1.0) / 5.0 * 15.0))
    score += max(0.0, min(20.0, (3.0 - abs(min(snap.breakout_dist_20d_pct, 3.0))) / 3.0 * 20.0))
    if snap.close > snap.sma20:
        score += 5
    if snap.close > snap.sma50:
        score += 5
    if snap.atr_ext_above_sma20 > 3.0:
        score -= min(15.0, (snap.atr_ext_above_sma20 - 3.0) * 3.0)
    return int(max(0, min(100, round(score))))


def _category_for_score(score: int, risk_reward: float | str | None) -> str:
    if isinstance(risk_reward, (int, float)) and risk_reward and risk_reward < 1.5:
        return "Avoid / Rejected"
    if score >= 75:
        return "A+ Setup"
    if score >= 60:
        return "Watchlist"
    if score >= 45:
        return "Early Momentum"
    return "Avoid / Rejected"


def _score_band_for_score(score: int) -> str:
    if score >= 75:
        return "a_plus"
    if score >= 60:
        return "watchlist"
    if score >= 45:
        return "early_momentum"
    return "avoid_rejected"


def _breakout_status(snap: IndicatorSnapshot) -> str:
    if snap.breakout_dist_20d_pct >= 0:
        return f"Breaking above 20-day high by {snap.breakout_dist_20d_pct:.1f}%"
    if snap.breakout_dist_20d_pct >= -2:
        return f"Near 20-day high ({abs(snap.breakout_dist_20d_pct):.1f}% below)"
    if snap.breakout_dist_50d_pct >= -3:
        return f"Near 50-day high ({abs(snap.breakout_dist_50d_pct):.1f}% below)"
    return "Not near breakout"


def _plain_snapshot_reason(snap: IndicatorSnapshot) -> str:
    parts = [snap.trend.replace("_", " ")]
    if snap.rvol_20 >= 1.5:
        parts.append(f"volume is active at {snap.rvol_20:.1f}x normal")
    if snap.breakout_dist_20d_pct >= 0:
        parts.append("price is above the prior 20-day high")
    elif snap.breakout_dist_20d_pct >= -2:
        parts.append("price is close to a 20-day breakout level")
    if snap.atr_ext_above_sma20 > 3:
        parts.append("but it is extended above the 20-day average")
    return "; ".join(parts) + "."


def _suggested_trigger(snap: IndicatorSnapshot) -> float:
    return max(snap.close * 1.01, snap.prior_high_20d * 1.001)


def _numeric_stop(snap: IndicatorSnapshot) -> float:
    return min(snap.sma20, snap.close - 1.5 * snap.atr14)


def _suggested_stop_area(snap: IndicatorSnapshot) -> str:
    return f"Consider invalidation below ${_numeric_stop(snap):.2f} or a close back under the 20-day average."


def _risk_note(category: str, risk_reward: float | str | None, warnings: list[str]) -> str:
    if warnings:
        return "; ".join(warnings[:2])
    if category == "A+ Setup":
        return "Strongest bucket, but wait for trigger and size risk normally."
    if category == "Watchlist":
        return "Interesting, but needs confirmation before acting."
    if category == "Early Momentum":
        return "Early or imperfect setup; use smaller size or wait for cleaner confirmation."
    if isinstance(risk_reward, (int, float)) and risk_reward and risk_reward < 1.5:
        return "Avoid for now: risk/reward is not attractive."
    return "Avoid for now: setup quality is not strong enough."


def generate_rejected_csv(
    scored_signals: list,
    snapshots: dict,
    output_dir: Path,
    run_date: date | None = None,
    filename_format: str = "{date}_rejected.csv",
) -> Path:
    """Write a CSV of signals that fell BELOW the main-report threshold.

    These are NOT recommendations. The CSV exists so the user can inspect
    what the system filtered out and understand its selectivity.
    """
    run_date = run_date or date.today()
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = filename_format.format(date=run_date.isoformat())
    filepath = output_dir / filename

    rows: list[dict] = []
    for rank, scored in enumerate(scored_signals, start=1):
        sig = scored.signal
        snap = snapshots.get(sig.ticker)
        if snap is None:
            continue

        # The single most relevant reason this got rejected
        primary_reason = _primary_rejection_reason(scored)
        breakout_level, distance_to_breakout_pct = _breakout_fields(sig, snap)

        row = {
            "Rank": rank,
            "Ticker": sig.ticker,
            "Score": scored.final_score,
            "Score Band": scored.score_band,
            "Primary Rejection Reason": primary_reason,
            "Setup Type": sig.setup_type,
            "Scanner Mode": sig.scanner_mode,
            "Strategy Module": sig.strategy_module,
            "Status": sig.status,
            "Current Price": round(snap.close, 2),
            "% Change Today": round(snap.pct_change_1d, 2),
            "RVOL": round(snap.rvol_20, 2),
            "Trend": snap.trend,
            "Dist from SMA20 %": round(snap.dist_from_sma20_pct, 2),
            "ATR Extension": round(snap.atr_ext_above_sma20, 2),
            "Entry Trigger": round(sig.entry_trigger, 2),
            "Stop Loss": round(sig.stop_loss, 2),
            "Target 1": round(sig.target_1, 2),
            "Risk/Reward": round(sig.risk_reward, 2),
            "entry_trigger": round(sig.entry_trigger, 2),
            "stop_loss": round(sig.stop_loss, 2),
            "target_1": round(sig.target_1, 2),
            "risk_reward": round(sig.risk_reward, 2),
            "invalidation": sig.invalidation,
            "what_to_wait_for": sig.wait_for,
            "breakout_level": breakout_level,
            "distance_to_breakout_pct": distance_to_breakout_pct,
            "Warnings": "; ".join(sig.warnings) if sig.warnings else "",
            "Reason": sig.reason,
        }
        # Add factor breakdown so user can see WHICH factors dragged score down
        for factor_name, factor_score in scored.factor_scores.items():
            row[f"factor_{factor_name}"] = round(factor_score, 1)
        rows.append(row)

    dynamic_columns = [c for row in rows for c in row if c not in REJECTED_COLUMNS]
    df = pd.DataFrame(rows, columns=REJECTED_COLUMNS + sorted(set(dynamic_columns)))
    df.to_csv(filepath, index=False, encoding="utf-8")
    return filepath


def _primary_rejection_reason(scored) -> str:
    """Identify the most likely reason a scored signal was rejected.

    Looks at the lowest-scoring factor (with weight > 0) and reports it.
    """
    for warning in scored.signal.warnings:
        if warning.startswith("missing_action_plan_fields:"):
            return "missing_action_plan_fields"
        if warning.startswith("generic_signal_not_actionable:"):
            return "generic_signal_not_actionable"
        if warning.startswith("rvol_below_min:"):
            return "rvol_below_min"
        if warning.startswith("downgraded_to_wait_for_pullback:"):
            return "downgraded_to_wait_for_pullback"

    # Get factor scores sorted ascending
    sorted_factors = sorted(scored.factor_scores.items(), key=lambda x: x[1])
    # Skip neutral 50.0 factors (those are placeholders for Phase 1 disabled features)
    real_factors = [
        (n, s) for n, s in sorted_factors
        if not (49.0 <= s <= 51.0 and n in {"sector_strength", "catalyst", "spread_quality"})
    ]
    if not real_factors:
        return "score below threshold (no dominant single reason)"
    weakest_name, weakest_score = real_factors[0]
    label_map = {
        "trend_strength":      "Weak trend",
        "setup_quality":       "Setup pattern not high quality",
        "relative_volume":     "Low relative volume",
        "rs_vs_primary":       "Weak relative strength vs SPY",
        "rs_vs_secondary":     "Weak relative strength vs QQQ",
        "dollar_volume":       "Low dollar volume",
        "price_action_quality":"Weak price action (close not near high)",
        "risk_reward":         "Risk/reward acceptable but not strong",
        "remaining_upside":    "Limited remaining upside to target",
    }
    label = label_map.get(weakest_name, weakest_name)
    return f"{label} (factor score {weakest_score:.0f}/100)"


def _breakout_fields(sig, snap) -> tuple[float | str, float | str]:
    """Return breakout level and positive distance-to-breakout for report rows."""
    breakout_level = sig.factor_inputs.get("prior_high") or sig.factor_inputs.get("breakout_level")
    if not breakout_level or snap is None or snap.close <= 0:
        return "", ""

    level = float(breakout_level)
    distance = (level / snap.close - 1.0) * 100.0
    return round(level, 2), round(distance, 2)
