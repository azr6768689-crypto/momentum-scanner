"""Analytics package.

Public API: re-exports the most commonly used names so callers can write
    from src.analytics import compute_snapshot, classify_market_regime
instead of digging into submodules.
"""

from .indicators import (
    # Constants
    TREND_UPTREND_STRONG,
    TREND_UPTREND_WEAK,
    TREND_SIDEWAYS as STOCK_TREND_SIDEWAYS,   # renamed to avoid clash w/ market regime
    TREND_DOWNTREND as STOCK_TREND_DOWNTREND,
    TREND_INSUFFICIENT,
    # Atomic indicators
    sma,
    sma20,
    sma50,
    sma200,
    atr,
    true_range,
    avg_volume,
    relative_volume,
    dollar_volume,
    pct_change,
    daily_pct_change,
    distance_from,
    distance_from_sma20,
    distance_from_sma50,
    atr_extension,
    rolling_high,
    prior_rolling_high,
    high_20d,
    high_50d,
    high_52w,
    breakout_distance,
    trend_condition,
    # Snapshot
    IndicatorSnapshot,
    compute_snapshot,
)

from .market_regime import (
    MarketRegime,
    classify_market_regime,
    TREND_UPTREND as MARKET_TREND_UPTREND,
    TREND_DOWNTREND as MARKET_TREND_DOWNTREND,
    TREND_SIDEWAYS as MARKET_TREND_SIDEWAYS,
    VOL_HIGH,
    VOL_NORMAL,
    VOL_LOW,
)


__all__ = [
    # Stock-level trend labels
    "TREND_UPTREND_STRONG",
    "TREND_UPTREND_WEAK",
    "STOCK_TREND_SIDEWAYS",
    "STOCK_TREND_DOWNTREND",
    "TREND_INSUFFICIENT",
    # Indicators
    "sma", "sma20", "sma50", "sma200",
    "atr", "true_range",
    "avg_volume", "relative_volume", "dollar_volume",
    "pct_change", "daily_pct_change",
    "distance_from", "distance_from_sma20", "distance_from_sma50",
    "atr_extension",
    "rolling_high", "prior_rolling_high",
    "high_20d", "high_50d", "high_52w",
    "breakout_distance",
    "trend_condition",
    "IndicatorSnapshot", "compute_snapshot",
    # Market regime
    "MarketRegime", "classify_market_regime",
    "MARKET_TREND_UPTREND", "MARKET_TREND_DOWNTREND", "MARKET_TREND_SIDEWAYS",
    "VOL_HIGH", "VOL_NORMAL", "VOL_LOW",
]
