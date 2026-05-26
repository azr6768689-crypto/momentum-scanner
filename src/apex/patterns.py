"""Setup pattern detection — Trade Ideas / IBD style labels."""

from __future__ import annotations

from src.apex.features import FeatureSet


def detect_setup(f: FeatureSet) -> tuple[str, list[str]]:
    flags: list[str] = []

    if f.breakout_20 >= 0 and f.rvol >= 1.5 and f.trend_stack >= 2:
        flags.append("פריצת 20 עם ווליום")
        return "Breakout 20D", flags

    if f.dist_52w >= -3 and f.breakout_50 >= -1 and f.rvol >= 1.3:
        flags.append("ליד שיא 52 שבועות")
        return "52W Power", flags

    if f.squeeze_pct <= 25 and f.breakout_20 >= -3 and f.trend_stack >= 2:
        flags.append("התכווצות לפני פריצה")
        return "Volatility Squeeze", flags

    if 0.08 <= f.ret_20d <= 35 and -8 <= f.dist_sma20 <= -1.5 and f.trend_stack >= 2:
        flags.append("פולבק לממוצע 20")
        return "Pullback 20", flags

    if f.ret_20d > 12 and -6 <= (f.close / f.sma20 - 1.0) * 100 <= 0:
        flags.append("דגל שורי")
        return "Bull Flag", flags

    if f.obv_slope > 0 and f.ret_20d > 5 and f.rvol >= 1.1:
        flags.append("צבירה (OBV)")
        return "Accumulation", flags

    if f.ret_63d < -5 and f.ret_20d > 3 and f.close > f.sma50:
        flags.append("היפוך בסיס")
        return "Reversal Base", flags

    if f.breakout_20 >= -2.5 and f.rvol >= 0.9:
        return "Near Breakout", flags

    return "No Setup", flags


def trend_grade(f: FeatureSet) -> str:
    if f.trend_stack >= 3 and f.sma20 > f.sma50 and f.adx14 >= 22:
        return "A — מגמה חזקה"
    if f.trend_stack >= 2 and f.close > f.sma50:
        return "B — מגמה עולה"
    if f.close > f.sma50:
        return "C — מעל MA50"
    if f.close > f.sma20:
        return "D — חלש"
    return "F — ירידה"


def institutional_grade_label(score: int) -> str:
    if score >= 85:
        return "מוסדי חזק"
    if score >= 72:
        return "מוסדי טוב"
    if score >= 58:
        return "בינוני+"
    if score >= 45:
        return "מוקדם"
    return "חלש"
