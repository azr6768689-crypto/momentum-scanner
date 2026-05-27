"""
Indicators.

All indicators in this file follow the same contract:

1. INPUT:  a pandas DataFrame with the standard OHLCV schema
           (columns: open, high, low, close, volume; DatetimeIndex named 'date').
2. OUTPUT: either a single pandas Series indexed the same as the input,
           OR a dict of scalars when only the "current" value matters.

NO LOOK-AHEAD. Every value at index ``t`` uses only data ``<= t``.

Vectorized implementations only (no per-row Python loops). pandas handles
NaN propagation correctly for warm-up periods — we never fill with zeros,
because that would silently corrupt downstream filters.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


# =============================================================================
# Trend condition labels (used by IndicatorSnapshot.trend)
# =============================================================================
TREND_UPTREND_STRONG = "uptrend_strong"     # price > SMA20 > SMA50, SMA50 rising
TREND_UPTREND_WEAK   = "uptrend_weak"       # price > SMA50 but not all aligned
TREND_SIDEWAYS       = "sideways"           # price oscillates around SMA50
TREND_DOWNTREND      = "downtrend"          # price < SMA50, SMA50 not rising
TREND_INSUFFICIENT   = "insufficient_data"  # not enough bars to decide


# =============================================================================
# Validation helpers
# =============================================================================

def _validate_ohlcv(df: pd.DataFrame) -> None:
    """Raise if DataFrame doesn't match the standard schema."""
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"OHLCV frame missing columns: {sorted(missing)}")
    if df.empty:
        # An empty frame is a valid input; downstream funcs handle it.
        return
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError(f"Index must be DatetimeIndex, got {type(df.index).__name__}")


# =============================================================================
# Moving averages
# =============================================================================

def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple moving average. NaN for the first ``period - 1`` rows."""
    if period <= 0:
        raise ValueError(f"sma period must be positive, got {period}")
    return series.rolling(window=period, min_periods=period).mean()


def sma20(df: pd.DataFrame) -> pd.Series:
    """20-day simple moving average of close."""
    _validate_ohlcv(df)
    return sma(df["close"], 20).rename("sma20")


def sma50(df: pd.DataFrame) -> pd.Series:
    """50-day simple moving average of close."""
    _validate_ohlcv(df)
    return sma(df["close"], 50).rename("sma50")


def sma200(df: pd.DataFrame) -> pd.Series:
    """200-day simple moving average of close. Useful for long trend filters."""
    _validate_ohlcv(df)
    return sma(df["close"], 200).rename("sma200")


# =============================================================================
# Average True Range (ATR)
# =============================================================================

def true_range(df: pd.DataFrame) -> pd.Series:
    """Wilder's True Range.

    TR = max(
        high - low,
        |high - previous_close|,
        |low  - previous_close|
    )
    """
    _validate_ohlcv(df)
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rename("true_range")


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (Wilder smoothing approximated by EMA).

    We use the EMA form which matches pandas-ta's default and is widely used.
    Wilder's original is also expressible as ``adjust=False`` ewm with
    alpha = 1/period, which is exactly what we use here.
    """
    if period <= 0:
        raise ValueError(f"atr period must be positive, got {period}")
    tr = true_range(df)
    # Wilder's smoothing: alpha = 1/period
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean().rename(f"atr{period}")


# =============================================================================
# Volume indicators
# =============================================================================

def avg_volume(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Average daily volume over ``period`` bars."""
    _validate_ohlcv(df)
    return df["volume"].rolling(window=period, min_periods=period).mean().rename(f"avg_volume_{period}")


def relative_volume(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Relative volume = today's volume / average volume over ``period`` bars.

    NOTE: when used on a daily bar mid-session, this is approximate —
    the "today" bar is only partially formed. Phase 2 will replace this
    with a proper intraday run-rate projection.
    """
    _validate_ohlcv(df)
    avg = avg_volume(df, period)
    rvol = df["volume"] / avg
    return rvol.rename(f"rvol_{period}")


def dollar_volume(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Average dollar volume over ``period`` bars = close * volume, then averaged.

    This is more meaningful for liquidity filtering than raw share volume,
    because a $500 stock and a $5 stock trade very differently.
    """
    _validate_ohlcv(df)
    dv = df["close"] * df["volume"]
    return dv.rolling(window=period, min_periods=period).mean().rename(f"dollar_volume_{period}")


# =============================================================================
# Returns
# =============================================================================

def pct_change(series: pd.Series, periods: int = 1) -> pd.Series:
    """Simple percentage change over ``periods`` bars. Result is in PERCENT (not 0–1)."""
    return (series.pct_change(periods=periods) * 100.0).rename(f"pct_change_{periods}")


def daily_pct_change(df: pd.DataFrame) -> pd.Series:
    """Today's percent change from yesterday's close."""
    _validate_ohlcv(df)
    return pct_change(df["close"], 1).rename("pct_change_1d")


# =============================================================================
# Distance / extension indicators
# =============================================================================

def distance_from(price: pd.Series, reference: pd.Series) -> pd.Series:
    """Percent distance of ``price`` from ``reference``. POSITIVE = price is above reference.

    Result is in PERCENT (e.g. 2.5 means price is 2.5% above reference).
    """
    return ((price / reference) - 1.0) * 100.0


def distance_from_sma20(df: pd.DataFrame) -> pd.Series:
    """Percent distance of close from SMA20. Positive = extended above SMA20."""
    _validate_ohlcv(df)
    return distance_from(df["close"], sma20(df)).rename("dist_from_sma20_pct")


def distance_from_sma50(df: pd.DataFrame) -> pd.Series:
    """Percent distance of close from SMA50. Positive = extended above SMA50."""
    _validate_ohlcv(df)
    return distance_from(df["close"], sma50(df)).rename("dist_from_sma50_pct")


def atr_extension(df: pd.DataFrame, reference: pd.Series, period: int = 14) -> pd.Series:
    """How many ATRs the close is above a reference series.

    Used to detect "too extended" conditions. If close is 3.5 ATRs above SMA20,
    the stock is stretched and chasing is risky.
    """
    _validate_ohlcv(df)
    a = atr(df, period)
    return ((df["close"] - reference) / a).rename(f"atr_ext_{period}")


# =============================================================================
# Highs (rolling lookback highs)
# =============================================================================
# Important detail: "20-day high" can mean two slightly different things.
#
#   (1) Highest CLOSE over the last N bars (inclusive of today).
#   (2) Highest HIGH over the last N bars (inclusive of today).
#
# For breakout detection we want (2) — a breakout means today's HIGH exceeds
# the highest high of the prior N bars. We expose both and use clear names.

def rolling_high(df: pd.DataFrame, period: int) -> pd.Series:
    """Highest high over the trailing ``period`` bars, INCLUDING today."""
    _validate_ohlcv(df)
    return df["high"].rolling(window=period, min_periods=period).max().rename(f"high_{period}")


def prior_rolling_high(df: pd.DataFrame, period: int) -> pd.Series:
    """Highest high over the ``period`` bars BEFORE today (excludes today).

    This is what breakout logic actually wants: did today's high break a level
    formed by prior bars?
    """
    _validate_ohlcv(df)
    return df["high"].shift(1).rolling(window=period, min_periods=period).max().rename(f"prior_high_{period}")


def high_20d(df: pd.DataFrame) -> pd.Series:
    """20-day high (highest high, inclusive of today)."""
    return rolling_high(df, 20).rename("high_20d")


def high_50d(df: pd.DataFrame) -> pd.Series:
    """50-day high."""
    return rolling_high(df, 50).rename("high_50d")


def high_52w(df: pd.DataFrame) -> pd.Series:
    """52-week high (~252 trading days).

    If the input has fewer than 252 bars at index ``t``, the value is NaN at
    that index — DO NOT pretend a 52-week high exists when it can't.
    """
    return rolling_high(df, 252).rename("high_52w")


# =============================================================================
# Breakout distance
# =============================================================================

def breakout_distance(df: pd.DataFrame, lookback: int) -> pd.Series:
    """Percent distance of today's close from the prior-N-bar high.

    POSITIVE  -> close has broken above the level (a breakout).
    NEGATIVE  -> close is still below the level.
    Magnitude tells how "fresh" or "extended" the breakout is.
    """
    _validate_ohlcv(df)
    prior_h = prior_rolling_high(df, lookback)
    return (((df["close"] / prior_h) - 1.0) * 100.0).rename(f"breakout_dist_{lookback}d_pct")


# =============================================================================
# Trend condition (single label per bar)
# =============================================================================

def trend_condition(
    df: pd.DataFrame,
    slope_lookback: int = 10,
) -> pd.Series:
    """Classify the trend at each bar.

    Labels (see module-level constants):
      - uptrend_strong:  close > SMA20 > SMA50 AND SMA50 rising over slope_lookback
      - uptrend_weak:    close > SMA50 (some alignment but not all)
      - sideways:        close near SMA50 (within ±2%) and SMA50 flat
      - downtrend:       close < SMA50 and SMA50 not rising
      - insufficient_data: not enough bars to compute SMA50 + slope

    The thresholds here are deliberately conservative defaults; the gating
    in scanners is enforced in src/scanners/, this is just a label per bar.
    """
    _validate_ohlcv(df)

    s20 = sma20(df)
    s50 = sma50(df)
    s50_slope = s50 - s50.shift(slope_lookback)   # absolute change over N bars
    s50_rising = s50_slope > 0
    s50_flat = s50_slope.abs() / s50 * 100.0 < 1.0   # < 1% drift over slope_lookback

    close = df["close"]
    pct_from_s50 = (close / s50 - 1.0) * 100.0

    labels = pd.Series(TREND_INSUFFICIENT, index=df.index, dtype="object")

    # Anywhere we have BOTH SMA20 and SMA50 computed, assign a real label
    have_data = s20.notna() & s50.notna() & s50_slope.notna()

    cond_strong = have_data & (close > s20) & (s20 > s50) & s50_rising
    cond_weak = have_data & (close > s50) & ~cond_strong
    cond_side = have_data & (pct_from_s50.abs() < 2.0) & s50_flat
    cond_down = have_data & (close < s50) & ~s50_rising

    # Order matters: strong > weak > sideways > down
    labels = labels.where(~cond_down, TREND_DOWNTREND)
    labels = labels.where(~cond_side, TREND_SIDEWAYS)
    labels = labels.where(~cond_weak, TREND_UPTREND_WEAK)
    labels = labels.where(~cond_strong, TREND_UPTREND_STRONG)

    return labels.rename("trend")


# =============================================================================
# IndicatorSnapshot — convenience aggregator for "what is true RIGHT NOW"
# =============================================================================
# Most scanners care only about the LATEST bar's values. Rather than have
# every scanner recompute everything and pick .iloc[-1], we offer a snapshot
# function that runs all the indicators once and returns the latest values.

@dataclass(frozen=True)
class IndicatorSnapshot:
    """Latest-bar values of every indicator we care about.

    All percentage fields are in PERCENT (e.g. 2.5 means 2.5%).
    """

    # When was this snapshot taken (last bar's index)
    as_of: pd.Timestamp

    # Price
    close: float
    open: float
    high: float
    low: float
    volume: float

    # Moving averages
    sma20: float
    sma50: float
    sma200: float | None

    # Volatility
    atr14: float

    # Volume
    avg_volume_20: float
    rvol_20: float
    dollar_volume_20: float

    # Returns
    pct_change_1d: float

    # Distances / extension
    dist_from_sma20_pct: float
    dist_from_sma50_pct: float
    atr_ext_above_sma20: float

    # Highs
    high_20d: float
    high_50d: float
    high_52w: float | None
    prior_high_20d: float
    prior_high_50d: float

    # Breakout distances (positive = past the level)
    breakout_dist_20d_pct: float
    breakout_dist_50d_pct: float

    # Labels
    trend: str

    # Sanity bookkeeping
    bars_available: int


def _safe_scalar(series: pd.Series) -> float | None:
    """Return the last value of a series as a Python float, or None if NaN/missing."""
    if series.empty:
        return None
    v = series.iloc[-1]
    if pd.isna(v):
        return None
    return float(v)


def compute_snapshot(df: pd.DataFrame) -> IndicatorSnapshot | None:
    """Compute every indicator and return the LATEST-BAR snapshot.

    Returns None if the frame is empty or doesn't have enough bars to compute
    the minimal set (we require SMA50 + ATR14, so at least 50 bars).

    All intermediate series (SMA20, SMA50, ATR14) are computed once and
    reused by dependent indicators to avoid redundant rolling-window passes.
    """
    _validate_ohlcv(df)
    if len(df) < 50:
        return None

    close = df["close"]

    s20 = sma(close, 20).rename("sma20")
    s50 = sma(close, 50).rename("sma50")
    s200 = sma(close, 200).rename("sma200") if len(df) >= 200 else None

    tr_series = true_range(df)
    a14 = tr_series.ewm(alpha=1.0 / 14, adjust=False, min_periods=14).mean().rename("atr14")

    av20 = df["volume"].rolling(window=20, min_periods=20).mean().rename("avg_volume_20")
    rv20 = (df["volume"] / av20).rename("rvol_20")
    dv20 = (close * df["volume"]).rolling(window=20, min_periods=20).mean().rename("dollar_volume_20")
    d1 = (close.pct_change(periods=1) * 100.0).rename("pct_change_1d")

    d_s20 = ((close / s20) - 1.0) * 100.0
    d_s50 = ((close / s50) - 1.0) * 100.0
    atr_ext_s20 = ((close - s20) / a14).rename("atr_ext_14")

    h20 = df["high"].rolling(window=20, min_periods=20).max().rename("high_20d")
    h50 = df["high"].rolling(window=50, min_periods=50).max().rename("high_50d")
    h52w = df["high"].rolling(window=252, min_periods=252).max().rename("high_52w") if len(df) >= 252 else None
    prior_h20 = df["high"].shift(1).rolling(window=20, min_periods=20).max().rename("prior_high_20")
    prior_h50 = df["high"].shift(1).rolling(window=50, min_periods=50).max().rename("prior_high_50")
    bd20 = ((close / prior_h20) - 1.0) * 100.0
    bd50 = ((close / prior_h50) - 1.0) * 100.0

    s50_slope = s50 - s50.shift(10)
    s50_rising = s50_slope > 0
    s50_flat = s50_slope.abs() / s50 * 100.0 < 1.0
    pct_from_s50 = (close / s50 - 1.0) * 100.0
    tr_labels = pd.Series(TREND_INSUFFICIENT, index=df.index, dtype="object")
    have_data = s20.notna() & s50.notna() & s50_slope.notna()
    cond_strong = have_data & (close > s20) & (s20 > s50) & s50_rising
    cond_weak = have_data & (close > s50) & ~cond_strong
    cond_side = have_data & (pct_from_s50.abs() < 2.0) & s50_flat
    cond_down = have_data & (close < s50) & ~s50_rising
    tr_labels = tr_labels.where(~cond_down, TREND_DOWNTREND)
    tr_labels = tr_labels.where(~cond_side, TREND_SIDEWAYS)
    tr_labels = tr_labels.where(~cond_weak, TREND_UPTREND_WEAK)
    tr_labels = tr_labels.where(~cond_strong, TREND_UPTREND_STRONG)
    tr = tr_labels.rename("trend")

    last = df.iloc[-1]

    # Required scalars — if any are NaN we don't have a usable snapshot
    s20_v = _safe_scalar(s20)
    s50_v = _safe_scalar(s50)
    atr_v = _safe_scalar(a14)
    if s20_v is None or s50_v is None or atr_v is None:
        return None

    return IndicatorSnapshot(
        as_of=df.index[-1],
        close=float(last["close"]),
        open=float(last["open"]),
        high=float(last["high"]),
        low=float(last["low"]),
        volume=float(last["volume"]),
        sma20=s20_v,
        sma50=s50_v,
        sma200=_safe_scalar(s200) if s200 is not None else None,
        atr14=atr_v,
        avg_volume_20=_safe_scalar(av20) or 0.0,
        rvol_20=_safe_scalar(rv20) or 0.0,
        dollar_volume_20=_safe_scalar(dv20) or 0.0,
        pct_change_1d=_safe_scalar(d1) or 0.0,
        dist_from_sma20_pct=_safe_scalar(d_s20) or 0.0,
        dist_from_sma50_pct=_safe_scalar(d_s50) or 0.0,
        atr_ext_above_sma20=_safe_scalar(atr_ext_s20) or 0.0,
        high_20d=_safe_scalar(h20) or float(last["close"]),
        high_50d=_safe_scalar(h50) or float(last["close"]),
        high_52w=_safe_scalar(h52w) if h52w is not None else None,
        prior_high_20d=_safe_scalar(prior_h20) or float(last["close"]),
        prior_high_50d=_safe_scalar(prior_h50) or float(last["close"]),
        breakout_dist_20d_pct=_safe_scalar(bd20) or 0.0,
        breakout_dist_50d_pct=_safe_scalar(bd50) or 0.0,
        trend=str(tr.iloc[-1]),
        bars_available=int(len(df)),
    )


__all__ = [
    # Constants
    "TREND_UPTREND_STRONG",
    "TREND_UPTREND_WEAK",
    "TREND_SIDEWAYS",
    "TREND_DOWNTREND",
    "TREND_INSUFFICIENT",
    # Atomic indicators
    "sma",
    "sma20",
    "sma50",
    "sma200",
    "true_range",
    "atr",
    "avg_volume",
    "relative_volume",
    "dollar_volume",
    "pct_change",
    "daily_pct_change",
    "distance_from",
    "distance_from_sma20",
    "distance_from_sma50",
    "atr_extension",
    "rolling_high",
    "prior_rolling_high",
    "high_20d",
    "high_50d",
    "high_52w",
    "breakout_distance",
    "trend_condition",
    # Snapshot
    "IndicatorSnapshot",
    "compute_snapshot",
]
