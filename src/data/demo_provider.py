"""
Demo data provider.

Generates deterministic synthetic OHLCV data so the system can be developed,
tested, and demonstrated WITHOUT any API key or network access.

Design goals:
- Realistic-looking price series with trends, pullbacks, breakouts.
- Different "personalities" per ticker (some trend hard, some chop, some
  consolidate then break) so the scanners produce a mix of setups.
- Deterministic: same seed -> same series, every run. This is essential for
  reproducible testing.
- Adheres strictly to the DataProvider contract.

This is NOT a Monte Carlo simulator and is NOT suitable for backtesting.
It exists to verify the plumbing works end-to-end before paying for data.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .base import (
    DataProvider, OHLCV_COLUMNS,
    SymbolMetadata, Quote,
    EXCHANGE_NYSE, EXCHANGE_NASDAQ, EXCHANGE_ARCA,
    ASSET_TYPE_COMMON, ASSET_TYPE_ETF,
)


# =============================================================================
# Ticker "personality" definitions
# =============================================================================
# Each personality is a tuple: (drift_per_day, daily_vol, regime_pattern)

# Known ETF tickers for demo metadata classification. Real providers will
# resolve this from reference data, not a hardcoded list.
_ETF_SYMBOLS: frozenset[str] = frozenset({
    "SPY", "QQQ", "IWM", "DIA", "VTI",
    "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC",
    "SMH", "SOXX", "XBI", "IBB", "ITB", "KRE",
    "GDX", "GLD", "SLV", "USO", "TLT", "HYG",
})
# We assign personalities by hashing the ticker so a given symbol always
# behaves the same way.

# Regime patterns describe how the trend behaves over the lookback window.
# - "strong_trend":    persistent uptrend; good for breakout/continuation
# - "compression":     low vol period followed by a breakout near end
# - "choppy":          range-bound; should NOT generate strong signals
# - "pullback":        uptrend then 3-5 bar pullback at the very end
# - "extended":        big move up at the end (should be flagged extended)
# - "downtrend":       declining; gates should filter these out
_PERSONALITIES = [
    ("strong_trend", 0.0010, 0.018),
    ("strong_trend", 0.0012, 0.020),
    ("compression",  0.0004, 0.014),
    ("compression",  0.0003, 0.012),
    ("choppy",       0.0001, 0.016),
    ("choppy",       0.0000, 0.018),
    ("pullback",     0.0008, 0.020),
    ("pullback",     0.0009, 0.022),
    ("extended",     0.0015, 0.025),
    ("downtrend",   -0.0008, 0.020),
]


def _personality_for(symbol: str) -> tuple[str, float, float]:
    """Deterministically pick a personality from the symbol string."""
    h = int(hashlib.md5(symbol.encode("utf-8")).hexdigest(), 16)
    return _PERSONALITIES[h % len(_PERSONALITIES)]


def _seed_for(symbol: str) -> int:
    """Deterministic numpy seed per symbol."""
    h = int(hashlib.md5(symbol.encode("utf-8")).hexdigest(), 16)
    return h % (2**32 - 1)


# =============================================================================
# Synthetic price generation
# =============================================================================

def _trading_days(start: date, end: date) -> pd.DatetimeIndex:
    """Generate a business-day index between start and end (inclusive).

    Uses pandas' 'B' frequency, which excludes weekends but does NOT exclude
    US holidays. For Phase 1 demo this is fine; market regime detection in
    later phases handles holidays via real data.
    """
    return pd.bdate_range(start=start, end=end, freq="B")


def _apply_regime(returns: np.ndarray, regime: str) -> np.ndarray:
    """Shape a raw return series into a recognizable regime pattern.

    The mutations here are intentionally aggressive so that synthetic data
    actually triggers the scanners — otherwise Phase 1 has nothing to show.
    """
    n = len(returns)
    out = returns.copy()

    if n < 30:
        return out

    if regime == "strong_trend":
        # Bias the last 60 bars up
        bias = np.linspace(0.0005, 0.002, min(60, n))
        out[-len(bias):] += bias

    elif regime == "compression":
        # Compress the last 30 bars to very low vol, then break out the last 3
        comp_len = min(30, n - 3)
        out[-comp_len:-3] *= 0.25
        # Big up days at the end with a small pullback
        out[-3] = 0.004
        out[-2] = 0.025   # breakout day
        out[-1] = 0.018   # follow-through

    elif regime == "choppy":
        # Mean-revert: alternate sign
        signs = np.where(np.arange(n) % 2 == 0, 1.0, -1.0)
        out = np.abs(out) * signs * 0.5

    elif regime == "pullback":
        # Strong leg up over 20 bars, then a 4-bar pullback
        leg_len = min(20, n - 4)
        out[-(leg_len + 4):-4] += 0.010
        out[-4:-1] = -0.012
        out[-1] = 0.008  # bounce candle

    elif regime == "extended":
        # Last 5 bars are huge up moves -> should trigger "too extended"
        out[-5:] = np.array([0.020, 0.025, 0.030, 0.022, 0.028])

    elif regime == "downtrend":
        # Bias the last 40 bars down
        bias = np.linspace(-0.0002, -0.0015, min(40, n))
        out[-len(bias):] += bias

    return out


def _generate_ohlcv(
    symbol: str,
    start: date,
    end: date,
    starting_price: float = 100.0,
) -> pd.DataFrame:
    """Generate a single ticker's synthetic OHLCV DataFrame."""
    rng = np.random.default_rng(_seed_for(symbol))
    regime, drift, vol = _personality_for(symbol)

    idx = _trading_days(start, end)
    n = len(idx)
    if n == 0:
        return DataProvider.empty_frame()

    # Daily log-returns: normal with drift + vol, then regime-shaped
    raw_returns = rng.normal(loc=drift, scale=vol, size=n)
    returns = _apply_regime(raw_returns, regime)

    # Price path
    close = starting_price * np.exp(np.cumsum(returns))

    # Build OHLC from close + intra-bar noise so wicks look realistic
    intra_vol = vol * 0.6
    open_noise = rng.normal(0.0, intra_vol * 0.3, size=n)
    high_noise = np.abs(rng.normal(0.0, intra_vol * 0.5, size=n))
    low_noise  = np.abs(rng.normal(0.0, intra_vol * 0.5, size=n))

    open_  = close * np.exp(open_noise)
    high   = np.maximum(open_, close) * np.exp(high_noise)
    low    = np.minimum(open_, close) * np.exp(-low_noise)

    # Volume — base level depends on ticker (hash again for variety),
    # with bursts on big-move days.
    base_volume = 800_000 + (_seed_for(symbol) % 5) * 600_000  # 0.8M - 3.8M
    move_magnitude = np.abs(returns)
    volume_multiplier = 1.0 + (move_magnitude / vol) * 0.7    # bigger move -> more volume
    daily_noise = rng.uniform(0.7, 1.3, size=n)
    volume = base_volume * volume_multiplier * daily_noise

    df = pd.DataFrame(
        {
            "open":   open_.astype(np.float64),
            "high":   high.astype(np.float64),
            "low":    low.astype(np.float64),
            "close":  close.astype(np.float64),
            "volume": volume.astype(np.float64),
        },
        index=pd.DatetimeIndex(idx, name="date"),
    )

    # Make sure OHLC invariants hold (high >= max(open, close), low <= min)
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"]  = df[["open", "low",  "close"]].min(axis=1)

    return df[OHLCV_COLUMNS]


# =============================================================================
# DemoProvider class
# =============================================================================

class DemoProvider(DataProvider):
    """No-network provider that emits deterministic synthetic OHLCV.

    Use this when DATA_PROVIDER=demo. Every other provider has the same
    interface, so swapping is a one-line change in the factory.
    """

    name = "demo"

    def __init__(self) -> None:
        # Starting prices vary per ticker, but deterministically.
        # This keeps prices realistic (between ~$15 and ~$500 typically).
        self._base_prices: dict[str, float] = {}

    # ---- DataProvider contract ------------------------------------------

    def is_available(self) -> bool:
        return True  # Demo is always available — that's the whole point.

    def get_daily_bars(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> pd.DataFrame:
        sym = self.normalize_symbol(symbol)
        starting_price = self._starting_price_for(sym)
        return _generate_ohlcv(sym, start, end, starting_price=starting_price)

    def get_minute_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        *,
        multiplier: int = 5,
        timespan: str = "minute",
    ) -> pd.DataFrame:
        """Synthetic intraday bars for live UI testing without Polygon."""
        _ = (multiplier, timespan)
        sym = self.normalize_symbol(symbol)
        daily = self.get_daily_bars(sym, end - timedelta(days=5), end)
        if daily.empty:
            return self.empty_frame()
        last = daily.iloc[-1]
        idx = pd.date_range(
            start=pd.Timestamp(date.today()).replace(hour=9, minute=30),
            end=pd.Timestamp(date.today()).replace(hour=16, minute=0),
            freq="5min",
        )
        n = len(idx)
        if n == 0:
            return self.empty_frame()
        rng = np.random.default_rng(_seed_for(sym) + 7)
        path = np.linspace(float(last["open"]), float(last["close"]), n)
        noise = rng.normal(0, float(last["close"]) * 0.002, size=n)
        close = path + noise
        high = np.maximum(close, float(last["high"])) * (1 + rng.uniform(0, 0.002, n))
        low = np.minimum(close, float(last["low"])) * (1 - rng.uniform(0, 0.002, n))
        vol = float(last["volume"]) / max(n, 1) * rng.uniform(0.5, 1.5, n)
        return pd.DataFrame(
            {
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": vol,
            },
            index=pd.DatetimeIndex(idx, name="date"),
        )[OHLCV_COLUMNS]

    def get_metadata(self, symbol: str) -> SymbolMetadata:
        """Deterministic synthetic metadata for demo mode.

        We use a small heuristic to classify ETFs (3-letter all caps that are
        well-known ETF tickers) vs common stock. Real providers will replace
        this with their reference data.
        """
        sym = self.normalize_symbol(symbol)
        is_etf = sym in _ETF_SYMBOLS
        seed = _seed_for(sym)
        rng = np.random.default_rng(seed)

        # Deterministic market cap: log-uniform between $500M and $3T
        log_lo, log_hi = np.log(500_000_000), np.log(3_000_000_000_000)
        market_cap = float(np.exp(rng.uniform(log_lo, log_hi)))

        # Float = 70-95% of market cap / price (rough proxy)
        starting_price = self._starting_price_for(sym)
        shares_out = market_cap / starting_price
        float_ratio = rng.uniform(0.7, 0.95)
        float_shares = shares_out * float_ratio

        # Pick an exchange deterministically
        if is_etf:
            exchange = EXCHANGE_ARCA
            asset_type = ASSET_TYPE_ETF
        else:
            # Hash decides NYSE vs NASDAQ
            exchange = EXCHANGE_NASDAQ if (seed % 2) else EXCHANGE_NYSE
            asset_type = ASSET_TYPE_COMMON

        return SymbolMetadata(
            symbol=sym,
            exchange=exchange,
            asset_type=asset_type,
            name=f"Demo Symbol {sym}",
            market_cap=market_cap,
            float_shares=float_shares,
            shares_outstanding=shares_out,
            is_active=True,
            sector=None,
            industry=None,
        )

    def get_quote(self, symbol: str) -> Quote | None:
        """Synthetic bid/ask quote — tight spread around last close.

        Demo provider doesn't have intraday data, so we approximate using
        the most recent close as the mid and a deterministic small spread.
        """
        sym = self.normalize_symbol(symbol)
        # Use today as endpoint
        df = self.get_daily_bars(sym, start=date.today(), end=date.today())
        # If empty (weekend, etc.), regenerate by widening the window
        if df.empty:
            from datetime import timedelta as _td
            df = self.get_daily_bars(sym, start=date.today() - _td(days=10), end=date.today())
        if df.empty:
            return None

        last_close = float(df["close"].iloc[-1])
        # Deterministic spread: 2-15 bps based on hash
        seed = _seed_for(sym)
        rng = np.random.default_rng(seed + 99)
        spread_bps = rng.uniform(2.0, 15.0)  # 0.02% to 0.15%
        half_spread = last_close * (spread_bps / 10000.0) / 2.0
        bid = last_close - half_spread
        ask = last_close + half_spread

        return Quote(
            symbol=sym,
            bid=round(bid, 4),
            ask=round(ask, 4),
            bid_size=100,
            ask_size=100,
            as_of=pd.Timestamp.now(),
        )

    # ---- helpers --------------------------------------------------------

    def _starting_price_for(self, symbol: str) -> float:
        """Pick a deterministic starting price per symbol, in [$15, $500]."""
        if symbol not in self._base_prices:
            seed = _seed_for(symbol)
            rng = np.random.default_rng(seed)
            # Log-uniform over [15, 500] gives a realistic spread
            log_lo, log_hi = np.log(15.0), np.log(500.0)
            self._base_prices[symbol] = float(np.exp(rng.uniform(log_lo, log_hi)))
        return self._base_prices[symbol]
