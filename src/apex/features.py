"""Vectorized feature engineering for Apex scanner."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.analytics.indicators import atr, sma


@dataclass(frozen=True)
class FeatureSet:
    close: float
    pct_1d: float
    ret_5d: float
    ret_20d: float
    ret_63d: float
    rvol: float
    atr14: float
    atr_pct: float
    rsi14: float
    adx14: float
    sma20: float
    sma50: float
    sma200: float | None
    dist_sma20: float
    dist_sma50: float
    dist_52w: float
    high_52w: float
    prior_high_20: float
    prior_high_50: float
    breakout_20: float
    breakout_50: float
    squeeze_pct: float
    obv_slope: float
    upper_wick_pct: float
    close_position: float
    trend_stack: int
    dollar_vol_20: float


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    plus_dm = high.diff().where(lambda s: (s > (-low.diff())) & (s > 0), 0.0)
    minus_dm = (-low.diff()).where(lambda s: (s > high.diff()) & (s > 0), 0.0)
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    atr_v = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_v
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_v
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _safe_last(series: pd.Series) -> float | None:
    if series.empty:
        return None
    v = series.iloc[-1]
    return None if pd.isna(v) else float(v)


def compute_features(df: pd.DataFrame) -> FeatureSet | None:
    if df is None or len(df) < 60:
        return None

    work = df.sort_index()
    close = work["close"]
    high = work["high"]
    low = work["low"]
    volume = work["volume"]

    s20 = sma(close, 20)
    s50 = sma(close, 50)
    s200 = sma(close, 200) if len(work) >= 200 else None
    a14 = atr(work, 14)
    avg_vol = volume.rolling(20, min_periods=20).mean()
    rvol_s = volume / avg_vol.replace(0, np.nan)

    ret_5 = (close.iloc[-1] / close.iloc[-6] - 1.0) * 100.0 if len(close) >= 6 else 0.0
    ret_20 = (close.iloc[-1] / close.iloc[-21] - 1.0) * 100.0 if len(close) >= 21 else 0.0
    ret_63 = (close.iloc[-1] / close.iloc[-64] - 1.0) * 100.0 if len(close) >= 64 else ret_20

    lookback_52 = min(252, len(work))
    high_52 = float(high.tail(lookback_52).max())
    prior_20 = float(high.shift(1).rolling(20, min_periods=20).max().iloc[-1])
    prior_50 = float(high.shift(1).rolling(50, min_periods=50).max().iloc[-1])
    last_close = float(close.iloc[-1])

    bb_mid = close.rolling(20, min_periods=20).mean()
    bb_std = close.rolling(20, min_periods=20).std()
    bb_width = (bb_std * 4 / bb_mid.replace(0, np.nan)).iloc[-20:]
    squeeze_pct = float(bb_width.rank(pct=True).iloc[-1] * 100) if len(bb_width.dropna()) >= 5 else 50.0

    obv = (np.sign(close.diff().fillna(0)) * volume).cumsum()
    obv_slope = float(obv.iloc[-1] - obv.iloc[-11]) if len(obv) >= 11 else 0.0

    last = work.iloc[-1]
    rng = max(float(last["high"] - last["low"]), 0.01)
    close_pos = float((last["close"] - last["low"]) / rng)
    upper_wick = float((last["high"] - max(last["open"], last["close"])) / rng)

    s20_v = _safe_last(s20)
    s50_v = _safe_last(s50)
    if s20_v is None or s50_v is None:
        return None

    stack = 0
    if last_close > s20_v:
        stack += 1
    if s20_v > s50_v:
        stack += 1
    if s200 is not None:
        s200_v = _safe_last(s200)
        if s200_v and last_close > s200_v:
            stack += 1

    return FeatureSet(
        close=last_close,
        pct_1d=float((close.iloc[-1] / close.iloc[-2] - 1.0) * 100.0) if len(close) >= 2 else 0.0,
        ret_5d=ret_5,
        ret_20d=ret_20,
        ret_63d=ret_63,
        rvol=float(_safe_last(rvol_s) or 1.0),
        atr14=float(_safe_last(a14) or 0.0),
        atr_pct=float((_safe_last(a14) or 0.0) / last_close * 100.0),
        rsi14=float(_safe_last(_rsi(close)) or 50.0),
        adx14=float(_safe_last(_adx(high, low, close)) or 0.0),
        sma20=s20_v,
        sma50=s50_v,
        sma200=_safe_last(s200) if s200 is not None else None,
        dist_sma20=(last_close / s20_v - 1.0) * 100.0,
        dist_sma50=(last_close / s50_v - 1.0) * 100.0,
        dist_52w=(last_close / high_52 - 1.0) * 100.0 if high_52 > 0 else 0.0,
        high_52w=high_52,
        prior_high_20=prior_20,
        prior_high_50=prior_50,
        breakout_20=(last_close / prior_20 - 1.0) * 100.0 if prior_20 > 0 else 0.0,
        breakout_50=(last_close / prior_50 - 1.0) * 100.0 if prior_50 > 0 else 0.0,
        squeeze_pct=squeeze_pct,
        obv_slope=obv_slope,
        upper_wick_pct=upper_wick,
        close_position=close_pos,
        trend_stack=stack,
        dollar_vol_20=float((close * volume).rolling(20, min_periods=20).mean().iloc[-1]),
    )


def relative_return(stock_df: pd.DataFrame, bench_df: pd.DataFrame | None, days: int = 20) -> float:
    if bench_df is None or len(stock_df) < days + 1 or len(bench_df) < days + 1:
        return 0.0
    s_ret = stock_df["close"].iloc[-1] / stock_df["close"].iloc[-days - 1] - 1.0
    b_ret = bench_df["close"].iloc[-1] / bench_df["close"].iloc[-days - 1] - 1.0
    return float((s_ret - b_ret) * 100.0)


def chart_payload(df: pd.DataFrame, bars: int = 90) -> list[dict]:
    tail = df.sort_index().tail(bars)
    out: list[dict] = []
    for idx, row in tail.iterrows():
        out.append({
            "d": idx.strftime("%Y-%m-%d"),
            "o": round(float(row["open"]), 2),
            "h": round(float(row["high"]), 2),
            "l": round(float(row["low"]), 2),
            "c": round(float(row["close"]), 2),
            "v": int(float(row["volume"])),
        })
    return out
