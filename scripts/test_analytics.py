"""
End-to-end test for the analytics layer.

What this script does:
1. Loads settings via src.config (sanity check the config layer).
2. Creates a DemoProvider and fetches ~3 years of bars for several tickers.
3. Runs every indicator and verifies:
     - shapes match the input
     - no look-ahead (tests rolling alignment)
     - reasonable numeric ranges
4. Computes an IndicatorSnapshot for each ticker.
5. Classifies market regime from SPY + QQQ.
6. Prints a human-readable report.

If everything passes, exits 0 and prints "ANALYTICS OK".
If anything fails, raises AssertionError with a clear message.

Usage from project root:
    python scripts/test_analytics.py
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

# Make 'src' importable when running this script directly
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from src.config import load_settings
from src.data import get_provider
from src.analytics import (
    # indicators
    sma20, sma50, atr, relative_volume, dollar_volume,
    daily_pct_change,
    distance_from_sma20, distance_from_sma50,
    high_20d, high_50d, high_52w,
    breakout_distance, trend_condition,
    compute_snapshot,
    # market regime
    classify_market_regime,
)


# Colors for terminal output (safe to skip on Windows)
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"


def _ok(msg: str) -> None:
    print(f"  {GREEN}OK{RESET}  {msg}")


def _info(msg: str) -> None:
    print(f"  {CYAN}--{RESET}  {msg}")


def _fail(msg: str) -> None:
    raise AssertionError(msg)


# =============================================================================
# Section 1 — Sanity checks per indicator
# =============================================================================

def test_indicator_basics(df: pd.DataFrame, symbol: str) -> None:
    print(f"\n[{symbol}] indicator basics ({len(df)} bars)")

    # SMA20
    s20 = sma20(df)
    assert len(s20) == len(df), "sma20 length mismatch"
    assert s20.iloc[:19].isna().all(), "sma20 should be NaN before bar 19"
    assert not pd.isna(s20.iloc[-1]), "sma20 should be defined at last bar"
    _ok(f"sma20 — last value ${s20.iloc[-1]:.2f}")

    # SMA50
    s50 = sma50(df)
    assert s50.iloc[:49].isna().all(), "sma50 should be NaN before bar 49"
    assert not pd.isna(s50.iloc[-1]), "sma50 should be defined at last bar"
    _ok(f"sma50 — last value ${s50.iloc[-1]:.2f}")

    # ATR
    a = atr(df, 14)
    assert not pd.isna(a.iloc[-1]), "atr should be defined at last bar"
    assert a.iloc[-1] > 0, "atr should be positive"
    _ok(f"atr(14) — last value ${a.iloc[-1]:.2f}")

    # RVOL
    rv = relative_volume(df, 20)
    assert not pd.isna(rv.iloc[-1]), "rvol should be defined at last bar"
    assert rv.iloc[-1] > 0, "rvol should be positive"
    _ok(f"rvol(20) — last value {rv.iloc[-1]:.2f}x")

    # Dollar volume
    dv = dollar_volume(df, 20)
    assert not pd.isna(dv.iloc[-1]), "dollar volume should be defined"
    assert dv.iloc[-1] > 0, "dollar volume should be positive"
    _ok(f"dollar_volume(20) — last value ${dv.iloc[-1]:,.0f}")

    # Daily pct change
    pc = daily_pct_change(df)
    assert pd.isna(pc.iloc[0]), "pct_change should be NaN on bar 0"
    _ok(f"pct_change_1d — last value {pc.iloc[-1]:+.2f}%")

    # Distances
    d20 = distance_from_sma20(df)
    d50 = distance_from_sma50(df)
    _ok(f"dist_from_sma20 — {d20.iloc[-1]:+.2f}%   dist_from_sma50 — {d50.iloc[-1]:+.2f}%")

    # Highs
    h20 = high_20d(df)
    h50 = high_50d(df)
    assert h20.iloc[-1] >= df["high"].iloc[-20:].max() - 1e-6, "20d high should equal rolling max"
    assert h50.iloc[-1] >= df["high"].iloc[-50:].max() - 1e-6, "50d high should equal rolling max"
    _ok(f"high_20d ${h20.iloc[-1]:.2f}   high_50d ${h50.iloc[-1]:.2f}")

    if len(df) >= 252:
        h52w = high_52w(df)
        assert not pd.isna(h52w.iloc[-1]), "52w high should be defined with enough data"
        _ok(f"high_52w ${h52w.iloc[-1]:.2f}")
    else:
        _info("not enough bars for 52w high (need 252)")

    # Breakout distances
    bd20 = breakout_distance(df, 20)
    bd50 = breakout_distance(df, 50)
    _ok(f"breakout_dist_20d {bd20.iloc[-1]:+.2f}%   breakout_dist_50d {bd50.iloc[-1]:+.2f}%")

    # Trend label
    tr = trend_condition(df)
    assert tr.iloc[-1] in {
        "uptrend_strong", "uptrend_weak", "sideways", "downtrend", "insufficient_data"
    }, f"unexpected trend label: {tr.iloc[-1]}"
    _ok(f"trend label: {tr.iloc[-1]}")


# =============================================================================
# Section 2 — No-lookahead test
# =============================================================================

def test_no_lookahead(df: pd.DataFrame) -> None:
    """Recompute on a truncated frame; values up to the truncation point
    must be identical to the full-frame computation. If not, an indicator
    is peeking at future data."""
    cut = len(df) - 30
    truncated = df.iloc[:cut].copy()

    # Pick a few indicators to check
    sma_full = sma20(df).iloc[:cut]
    sma_trunc = sma20(truncated)
    assert sma_full.equals(sma_trunc), "sma20 leaks future data"

    atr_full = atr(df, 14).iloc[:cut]
    atr_trunc = atr(truncated, 14)
    # ATR uses EMA — minor floating-point differences are not expected here
    # because both series start from the same initial values.
    assert (atr_full.fillna(-1) - atr_trunc.fillna(-1)).abs().max() < 1e-9, "atr leaks future data"

    bd_full = breakout_distance(df, 20).iloc[:cut]
    bd_trunc = breakout_distance(truncated, 20)
    assert bd_full.equals(bd_trunc), "breakout_distance leaks future data"

    _ok("no-lookahead check passed (sma20, atr14, breakout_dist)")


# =============================================================================
# Section 3 — Snapshot
# =============================================================================

def test_snapshot(df: pd.DataFrame, symbol: str) -> None:
    snap = compute_snapshot(df)
    assert snap is not None, f"snapshot should not be None for {symbol} (len={len(df)})"

    # Quick coherence checks
    assert snap.close > 0
    assert snap.sma20 > 0
    assert snap.sma50 > 0
    assert snap.atr14 > 0
    assert snap.bars_available == len(df)

    print(
        f"\n  {YELLOW}snapshot[{symbol}]{RESET}  "
        f"close=${snap.close:.2f}  sma20=${snap.sma20:.2f}  sma50=${snap.sma50:.2f}  "
        f"atr14=${snap.atr14:.2f}  rvol={snap.rvol_20:.2f}x"
    )
    print(
        f"             dist_sma20={snap.dist_from_sma20_pct:+.2f}%  "
        f"dist_sma50={snap.dist_from_sma50_pct:+.2f}%  "
        f"breakout_20d={snap.breakout_dist_20d_pct:+.2f}%  "
        f"trend={snap.trend}"
    )


# =============================================================================
# Section 4 — Market regime
# =============================================================================

def test_market_regime(provider, start: date, end: date) -> None:
    print(f"\n{CYAN}=== Market regime ==={RESET}")
    spy = provider.get_daily_bars("SPY", start, end)
    qqq = provider.get_daily_bars("QQQ", start, end)
    assert not spy.empty, "SPY data should not be empty"
    assert not qqq.empty, "QQQ data should not be empty"

    regime = classify_market_regime(spy, qqq, vix=None)
    _ok(f"trend_label:      {regime.trend_label}")
    _ok(f"volatility_label: {regime.volatility_label}")
    _ok(f"composite:        {regime.composite_label}")
    _ok(f"confidence:       {regime.confidence}/100")
    _info(
        f"SPY close=${regime.spy_close:.2f}  "
        f"vs SMA50 {regime.spy_pct_above_sma50:+.2f}%  "
        f"SMA50 slope {regime.spy_sma50_slope_pct:+.2f}%"
    )
    _info(
        f"QQQ close=${regime.qqq_close:.2f}  "
        f"vs SMA50 {regime.qqq_pct_above_sma50:+.2f}%  "
        f"agrees with SPY: {regime.qqq_agrees_with_spy}"
    )
    _info(f"realized vol 20d (annualized): {regime.realized_vol_annualized_pct:.1f}%")
    _info(f"favorable for long momentum: {regime.is_favorable_for_long_momentum()}")


# =============================================================================
# Main
# =============================================================================

def main() -> int:
    print(f"{CYAN}=== Analytics test suite ==={RESET}")
    settings = load_settings()
    provider = get_provider(settings)
    print(f"  Provider: {provider.name}")

    # Fetch ~3 years so we have enough for 52-week high
    end = date.today()
    start = end - timedelta(days=365 * 3)

    test_symbols = ["AAPL", "MSFT", "TSLA", "NVDA", "AMZN"]
    for sym in test_symbols:
        df = provider.get_daily_bars(sym, start, end)
        assert not df.empty, f"{sym} returned empty frame"
        test_indicator_basics(df, sym)
        test_snapshot(df, sym)

    # No-lookahead check (use one of the frames we already have)
    df_check = provider.get_daily_bars("AAPL", start, end)
    print()
    test_no_lookahead(df_check)

    # Market regime
    test_market_regime(provider, start, end)

    print(f"\n{GREEN}ANALYTICS OK{RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
