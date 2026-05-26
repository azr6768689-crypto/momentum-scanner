"""Market regime — SPY / QQQ context for long bias."""

from __future__ import annotations

import pandas as pd

from src.apex.features import compute_features
from src.apex.models import MarketContext


def _trend_label(df: pd.DataFrame | None) -> str:
    f = compute_features(df) if df is not None else None
    if f is None:
        return "לא זמין"
    if f.trend_stack >= 3:
        return "עולה חזק"
    if f.close > f.sma50:
        return "עולה"
    if f.close < f.sma50:
        return "יורד"
    return "מעורב"


def build_market_context(
    spy: pd.DataFrame | None,
    qqq: pd.DataFrame | None,
    iwm: pd.DataFrame | None = None,
) -> MarketContext:
    scores: list[int] = []
    notes: list[str] = []

    for name, df in (("SPY", spy), ("QQQ", qqq), ("IWM", iwm)):
        f = compute_features(df) if df is not None else None
        if f is None:
            continue
        local = 50
        if f.close > f.sma20 > f.sma50:
            local += 22
            notes.append(f"{name} במגמה מושלמת")
        elif f.close > f.sma50:
            local += 12
            notes.append(f"{name} מעל MA50")
        else:
            local -= 18
            notes.append(f"{name} חלש")
        if f.pct_1d > 0:
            local += min(8, int(f.pct_1d * 2))
        if f.breakout_20 >= -1:
            local += 6
        scores.append(max(0, min(100, local)))

    if not scores:
        return MarketContext(
            regime="לא זמין",
            score=50,
            spy_trend="לא זמין",
            qqq_trend="לא זמין",
            long_bias="ניטרלי",
            note="אין דאטה למדדי שוק",
        )

    avg = int(round(sum(scores) / len(scores)))
    if avg >= 72:
        regime = "Risk-On"
        bias = "תומך לונג"
    elif avg >= 55:
        regime = "שוק חיובי"
        bias = "תומך חלקית"
    elif avg >= 42:
        regime = "מעורב"
        bias = "זהירות"
    else:
        regime = "Risk-Off"
        bias = "לא תומך"

    return MarketContext(
        regime=regime,
        score=avg,
        spy_trend=_trend_label(spy),
        qqq_trend=_trend_label(qqq),
        long_bias=bias,
        note="; ".join(notes),
    )
