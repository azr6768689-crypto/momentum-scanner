"""
Market regime classifier.

Determines the broad market environment so that:
1. Scanners can throttle aggressiveness in unfavorable regimes.
2. Reports display the current regime prominently.
3. Phase 6 backtests can stratify performance by regime.

The classifier is intentionally simple and transparent. Sophisticated
regime detection (HMMs, Markov-switching models) is a research topic of its
own; for Phase 1 we use rule-based labels off SPY + QQQ that any trader
can sanity-check by glancing at a chart.

INPUTS:
- SPY daily OHLCV (required)
- QQQ daily OHLCV (required; confirms or contradicts SPY)
- VIX daily close (optional; if absent, we approximate with realized vol)

OUTPUTS:
- A MarketRegime dataclass with:
    trend_label:      "uptrend" | "downtrend" | "sideways"
    volatility_label: "high_vol" | "normal_vol" | "low_vol"
    composite_label:  human-readable summary
    plus the raw inputs used so the report can show the math
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .indicators import sma, atr, _validate_ohlcv


# =============================================================================
# Trend labels
# =============================================================================
TREND_UPTREND   = "uptrend"
TREND_DOWNTREND = "downtrend"
TREND_SIDEWAYS  = "sideways"

# Volatility labels
VOL_HIGH   = "high_vol"
VOL_NORMAL = "normal_vol"
VOL_LOW    = "low_vol"


# =============================================================================
# Dataclass
# =============================================================================

@dataclass(frozen=True)
class MarketRegime:
    """Snapshot of the current market regime."""

    as_of: pd.Timestamp

    # Headline labels
    trend_label: str          # uptrend / downtrend / sideways
    volatility_label: str     # high_vol / normal_vol / low_vol
    composite_label: str      # e.g. "SPY uptrend, normal volatility"

    # SPY measurements
    spy_close: float
    spy_sma50: float
    spy_sma200: float | None
    spy_pct_above_sma50: float
    spy_pct_above_sma200: float | None
    spy_sma50_slope_pct: float          # SMA50 slope over slope_lookback bars, in %

    # QQQ measurements (confirmation)
    qqq_close: float
    qqq_sma50: float
    qqq_pct_above_sma50: float
    qqq_sma50_slope_pct: float
    qqq_agrees_with_spy: bool

    # Volatility measurements
    vix_close: float | None             # None if VIX not provided
    realized_vol_annualized_pct: float  # SPY 20-day realized vol, annualized

    # How confident we are (rough heuristic, 0-100)
    confidence: int

    def is_favorable_for_long_momentum(self) -> bool:
        """Convenience flag used by scanners."""
        # Long momentum works best in uptrend + normal vol.
        # Uptrend + high vol = still tradeable but selective.
        # Anything else = throttle.
        if self.trend_label == TREND_DOWNTREND:
            return False
        if self.trend_label == TREND_SIDEWAYS and self.volatility_label == VOL_HIGH:
            return False
        return True


# =============================================================================
# Helpers
# =============================================================================

def _trend_for_index(
    df: pd.DataFrame,
    slope_lookback: int = 10,
) -> tuple[str, float, float, float, float | None, float | None]:
    """Classify trend for a single index (SPY or QQQ).

    Returns:
        (label, close, sma50, sma50_slope_pct, sma200 or None, pct_above_sma200 or None)
    """
    _validate_ohlcv(df)
    if len(df) < 50:
        # Can't decide; default to sideways with NaN-ish numbers
        last_close = float(df["close"].iloc[-1]) if not df.empty else 0.0
        return TREND_SIDEWAYS, last_close, last_close, 0.0, None, None

    s50 = sma(df["close"], 50)
    s50_last = float(s50.iloc[-1])
    s50_prev = float(s50.iloc[-1 - slope_lookback]) if len(s50) > slope_lookback else s50_last
    slope_pct = ((s50_last / s50_prev) - 1.0) * 100.0 if s50_prev > 0 else 0.0

    close = float(df["close"].iloc[-1])
    pct_above_s50 = ((close / s50_last) - 1.0) * 100.0

    s200_last: float | None = None
    pct_above_s200: float | None = None
    if len(df) >= 200:
        s200 = sma(df["close"], 200)
        s200_last = float(s200.iloc[-1])
        if s200_last > 0:
            pct_above_s200 = ((close / s200_last) - 1.0) * 100.0

    # Rules:
    # - Uptrend:   close > SMA50 AND SMA50 slope > 0
    # - Downtrend: close < SMA50 AND SMA50 slope < 0
    # - Sideways:  anything else (mixed signals, flat SMA50)
    if close > s50_last and slope_pct > 0.0:
        label = TREND_UPTREND
    elif close < s50_last and slope_pct < 0.0:
        label = TREND_DOWNTREND
    else:
        label = TREND_SIDEWAYS

    return label, close, s50_last, slope_pct, s200_last, pct_above_s200


def _realized_vol_annualized(close: pd.Series, window: int = 20) -> float:
    """Annualized realized volatility of daily log returns, in PERCENT.

    sqrt(252) * stddev(log returns), expressed as a percent.
    Returns 0.0 if we don't have enough bars.
    """
    if len(close) < window + 1:
        return 0.0
    log_ret = np.log(close / close.shift(1))
    std = log_ret.iloc[-window:].std()
    if pd.isna(std):
        return 0.0
    return float(std * np.sqrt(252) * 100.0)


def _classify_volatility(
    vix_close: float | None,
    realized_vol_pct: float,
    vix_high_threshold: float = 25.0,
    vix_low_threshold: float = 13.0,
) -> str:
    """Pick a volatility bucket.

    If VIX is available, use it. Otherwise fall back to realized vol on SPY,
    using approximate-equivalent thresholds (realized vol is typically
    a touch lower than implied vol, but close enough for a label).
    """
    if vix_close is not None:
        if vix_close >= vix_high_threshold:
            return VOL_HIGH
        if vix_close <= vix_low_threshold:
            return VOL_LOW
        return VOL_NORMAL

    # Fallback: realized vol thresholds calibrated loosely vs VIX
    if realized_vol_pct >= 22.0:
        return VOL_HIGH
    if realized_vol_pct <= 11.0:
        return VOL_LOW
    return VOL_NORMAL


# =============================================================================
# Public API
# =============================================================================

def classify_market_regime(
    spy: pd.DataFrame,
    qqq: pd.DataFrame,
    vix: pd.DataFrame | None = None,
    slope_lookback: int = 10,
    vix_high_threshold: float = 25.0,
    vix_low_threshold: float = 13.0,
) -> MarketRegime:
    """Classify the current market regime from SPY + QQQ (+ optional VIX).

    Args:
        spy:  daily OHLCV DataFrame for SPY. Required.
        qqq:  daily OHLCV DataFrame for QQQ. Required.
        vix:  daily OHLCV DataFrame for VIX. Optional. We use only the close.
        slope_lookback: how many bars to look back when measuring SMA50 slope.
        vix_high_threshold / vix_low_threshold: VIX cutoffs for vol buckets.

    Returns:
        MarketRegime with both labels and the raw numbers behind them.

    Raises:
        ValueError: if SPY or QQQ is empty.
    """
    if spy.empty:
        raise ValueError("classify_market_regime: SPY DataFrame is empty")
    if qqq.empty:
        raise ValueError("classify_market_regime: QQQ DataFrame is empty")

    # 1. Trend from SPY (headline) and QQQ (confirmation)
    (spy_label, spy_close, spy_s50, spy_slope_pct,
     spy_s200, spy_pct_s200) = _trend_for_index(spy, slope_lookback)
    (qqq_label, qqq_close, qqq_s50, qqq_slope_pct,
     _qqq_s200, _qqq_pct_s200) = _trend_for_index(qqq, slope_lookback)

    spy_pct_s50 = ((spy_close / spy_s50) - 1.0) * 100.0 if spy_s50 > 0 else 0.0
    qqq_pct_s50 = ((qqq_close / qqq_s50) - 1.0) * 100.0 if qqq_s50 > 0 else 0.0

    qqq_agrees = qqq_label == spy_label

    # Headline trend label: SPY decides, with downgrade if QQQ disagrees on uptrend
    trend_label = spy_label
    if spy_label == TREND_UPTREND and qqq_label == TREND_DOWNTREND:
        # Sharp divergence -> rotation; treat as sideways for safety
        trend_label = TREND_SIDEWAYS

    # 2. Volatility
    vix_close: float | None = None
    if vix is not None and not vix.empty:
        vix_close = float(vix["close"].iloc[-1])
    realized_vol = _realized_vol_annualized(spy["close"], window=20)
    vol_label = _classify_volatility(
        vix_close=vix_close,
        realized_vol_pct=realized_vol,
        vix_high_threshold=vix_high_threshold,
        vix_low_threshold=vix_low_threshold,
    )

    # 3. Composite label (human readable)
    composite = f"SPY {trend_label}, {vol_label.replace('_', ' ')}"
    if not qqq_agrees:
        composite += " (QQQ divergent)"

    # 4. Confidence heuristic
    #    - Bigger pct-above-SMA50 and steeper slope => more confidence
    #    - Disagreement between SPY and QQQ reduces confidence
    confidence = 50
    confidence += min(20, int(abs(spy_pct_s50) * 4))          # up to +20 for distance
    confidence += min(15, int(abs(spy_slope_pct) * 5))        # up to +15 for slope
    if not qqq_agrees:
        confidence -= 15
    confidence = max(0, min(100, confidence))

    return MarketRegime(
        as_of=spy.index[-1],
        trend_label=trend_label,
        volatility_label=vol_label,
        composite_label=composite,
        spy_close=spy_close,
        spy_sma50=spy_s50,
        spy_sma200=spy_s200,
        spy_pct_above_sma50=spy_pct_s50,
        spy_pct_above_sma200=spy_pct_s200,
        spy_sma50_slope_pct=spy_slope_pct,
        qqq_close=qqq_close,
        qqq_sma50=qqq_s50,
        qqq_pct_above_sma50=qqq_pct_s50,
        qqq_sma50_slope_pct=qqq_slope_pct,
        qqq_agrees_with_spy=qqq_agrees,
        vix_close=vix_close,
        realized_vol_annualized_pct=realized_vol,
        confidence=confidence,
    )


__all__ = [
    "MarketRegime",
    "classify_market_regime",
    "TREND_UPTREND",
    "TREND_DOWNTREND",
    "TREND_SIDEWAYS",
    "VOL_HIGH",
    "VOL_NORMAL",
    "VOL_LOW",
]
