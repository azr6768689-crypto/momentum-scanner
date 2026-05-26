"""Composite Apex scoring — institutional momentum rank."""

from __future__ import annotations

from src.apex.features import FeatureSet, relative_return
from src.apex.models import MarketContext
from src.apex.patterns import detect_setup, institutional_grade_label, trend_grade
import pandas as pd


def rs_percentile(rs_values: dict[str, float]) -> dict[str, int]:
    if not rs_values:
        return {}
    items = sorted(rs_values.items(), key=lambda x: x[1])
    n = len(items)
    if n == 1:
        return {items[0][0]: 50}
    out: dict[str, int] = {}
    for i, (sym, _) in enumerate(items):
        out[sym] = max(1, min(99, int(round(100 * i / (n - 1)))))
    return out


def score_stock(
    ticker: str,
    f: FeatureSet,
    *,
    rs_rating: int,
    market: MarketContext,
    spy_df: pd.DataFrame | None,
    qqq_df: pd.DataFrame | None,
    stock_df: pd.DataFrame,
) -> dict:
    setup, flags = detect_setup(f)
    grade = trend_grade(f)

    rs_spy = relative_return(stock_df, spy_df, 20)
    rs_qqq = relative_return(stock_df, qqq_df, 20)

    momentum = 0
    momentum += min(25, max(0, int(f.ret_20d * 1.2)))
    momentum += min(15, max(0, int(rs_rating * 0.15)))
    momentum += min(12, max(0, int(f.trend_stack * 4)))

    volume = 0
    if f.rvol >= 2.0:
        volume += 22
    elif f.rvol >= 1.5:
        volume += 16
    elif f.rvol >= 1.2:
        volume += 10
    elif f.rvol >= 0.9:
        volume += 4
    if f.obv_slope > 0:
        volume += 8

    timing = 0
    if -2 <= f.breakout_20 <= 3:
        timing += 18
    elif f.breakout_20 > 0:
        timing += 12
    if f.squeeze_pct <= 30:
        timing += 10
    if 52 <= f.rsi14 <= 68:
        timing += 8
    if f.adx14 >= 20:
        timing += 6

    inst = 0
    if rs_spy >= 5:
        inst += 18
    elif rs_spy >= 0:
        inst += 10
    if rs_qqq >= 5:
        inst += 12
    elif rs_qqq >= 0:
        inst += 8
    if f.close_position >= 0.7 and f.upper_wick_pct <= 0.3:
        inst += 14
    elif f.close_position >= 0.55:
        inst += 6
    if setup not in {"No Setup", "Near Breakout"}:
        inst += 12

    market_adj = 0
    if market.score >= 70:
        market_adj = 8
    elif market.score >= 55:
        market_adj = 4
    elif market.score < 42:
        market_adj = -10

    penalty = 0
    if f.dist_sma20 > 12:
        penalty += 15
        flags.append("מתוח מעל MA20")
    if f.rsi14 > 78:
        penalty += 10
        flags.append("RSI גבוה")
    if f.dist_52w < -25:
        penalty += 8

    apex = max(0, min(100, momentum + volume + timing + inst + market_adj - penalty))
    inst_score = max(0, min(100, inst + int(rs_rating * 0.2)))

    risk = max(f.atr14 * 1.5, f.close * 0.02, 0.01)
    entry = max(f.close * 1.003, f.prior_high_20 * 1.001)
    stop = min(f.sma20, f.close - risk)
    target_1 = entry + 2.0 * (entry - stop)
    target_2 = entry + 3.5 * (entry - stop)
    rr = (target_1 - entry) / max(entry - stop, 0.01)

    trigger = f"פריצה מעל ${entry:.2f} + RVOL≥1.5"
    if setup == "Volatility Squeeze":
        trigger = f"פריצה מהתכווצות מעל ${f.prior_high_20:.2f}"

    summary_parts = [
        f"RS {rs_rating}",
        setup,
        grade.split("—")[0].strip(),
        f"שוק {market.regime}",
    ]

    return {
        "apex_score": int(apex),
        "rs_rating": rs_rating,
        "trend_grade": grade,
        "setup_type": setup,
        "institutional_grade": institutional_grade_label(inst_score),
        "institutional_score": inst_score,
        "timing_score": min(100, timing),
        "volume_score": min(100, volume),
        "risk_reward": float(rr),
        "rs_vs_spy_20d": rs_spy,
        "rs_vs_qqq_20d": rs_qqq,
        "entry": float(entry),
        "stop": float(stop),
        "target_1": float(target_1),
        "target_2": float(target_2),
        "trigger": trigger,
        "summary": " · ".join(summary_parts),
        "flags": flags,
    }
