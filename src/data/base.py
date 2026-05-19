"""
Abstract data provider interface.

Every concrete provider (Demo, Tiingo, Polygon, Alpaca) implements this base.
The rest of the system depends only on this interface, so swapping providers
is a one-line change in src/data/__init__.py.

Group G change: providers now also expose:
- get_metadata(symbol) -> SymbolMetadata: exchange, asset_type, float, market_cap, etc.
- get_quote(symbol) -> Quote | None: latest bid/ask if available
These methods MAY return None or fall back to defaults. Strategies and the
liquidity layer handle None gracefully (no spread filter if no quotes, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

import pandas as pd


# =============================================================================
# Standard column schema — all providers must conform
# =============================================================================
OHLCV_COLUMNS: list[str] = ["open", "high", "low", "close", "volume"]


# =============================================================================
# Asset type taxonomy
# =============================================================================
# What kind of security is this. The liquidity layer excludes certain types.
ASSET_TYPE_COMMON      = "common_stock"   # plain common shares
ASSET_TYPE_ETF         = "etf"            # exchange-traded fund
ASSET_TYPE_ADR         = "adr"            # American Depositary Receipt
ASSET_TYPE_PREFERRED   = "preferred"      # preferred shares — excluded
ASSET_TYPE_WARRANT     = "warrant"        # warrant — excluded
ASSET_TYPE_RIGHT       = "right"          # right — excluded
ASSET_TYPE_UNIT        = "unit"           # unit (often SPAC) — excluded
ASSET_TYPE_TEST        = "test"           # test issue — excluded
ASSET_TYPE_UNKNOWN     = "unknown"        # unknown — treated as low quality

# Asset types acceptable for scanning
TRADABLE_ASSET_TYPES: set[str] = {
    ASSET_TYPE_COMMON,
    ASSET_TYPE_ETF,
    ASSET_TYPE_ADR,
}

# Asset types we explicitly exclude
EXCLUDED_ASSET_TYPES: set[str] = {
    ASSET_TYPE_PREFERRED,
    ASSET_TYPE_WARRANT,
    ASSET_TYPE_RIGHT,
    ASSET_TYPE_UNIT,
    ASSET_TYPE_TEST,
}


# =============================================================================
# Exchange taxonomy
# =============================================================================
EXCHANGE_NYSE     = "NYSE"
EXCHANGE_NASDAQ   = "NASDAQ"
EXCHANGE_AMEX     = "AMEX"           # NYSE American
EXCHANGE_ARCA     = "ARCA"           # NYSE Arca (ETFs)
EXCHANGE_BATS     = "BATS"           # BATS (now part of Cboe)
EXCHANGE_OTC      = "OTC"            # over-the-counter — excluded
EXCHANGE_PINK     = "PINK"           # pink sheets — excluded
EXCHANGE_UNKNOWN  = "UNKNOWN"

# Exchanges we accept
ACCEPTABLE_EXCHANGES: set[str] = {
    EXCHANGE_NYSE,
    EXCHANGE_NASDAQ,
    EXCHANGE_AMEX,
    EXCHANGE_ARCA,
    EXCHANGE_BATS,
}

# Exchanges we exclude
EXCLUDED_EXCHANGES: set[str] = {
    EXCHANGE_OTC,
    EXCHANGE_PINK,
}


# =============================================================================
# Dataclasses
# =============================================================================

@dataclass(frozen=True)
class BarRequest:
    """A request for historical bars."""
    symbol: str
    start: date
    end: date


@dataclass(frozen=True)
class SymbolMetadata:
    """Static or slow-changing facts about a symbol.

    Any field may be None when the provider doesn't have it. The liquidity
    layer treats missing data as a quality penalty, not a hard exclusion,
    except for `exchange` and `asset_type` which gate inclusion.
    """
    symbol: str
    exchange: str = EXCHANGE_UNKNOWN
    asset_type: str = ASSET_TYPE_UNKNOWN

    # Optional quality signals
    name: str | None = None
    market_cap: float | None = None          # dollars
    float_shares: float | None = None        # shares
    shares_outstanding: float | None = None  # shares
    is_active: bool = True                   # delisted/test symbols set False
    sector: str | None = None
    industry: str | None = None

    def is_tradable(self) -> bool:
        """Quick gate: must be on an acceptable exchange and tradable type."""
        if not self.is_active:
            return False
        if self.exchange in EXCLUDED_EXCHANGES:
            return False
        if self.asset_type in EXCLUDED_ASSET_TYPES:
            return False
        return True


@dataclass(frozen=True)
class Quote:
    """Latest top-of-book quote (bid/ask). Optional — provider may return None.

    spread_pct = (ask - bid) / mid_price * 100   (in percent)
    """
    symbol: str
    bid: float
    ask: float
    bid_size: int | None = None
    ask_size: int | None = None
    as_of: pd.Timestamp | None = None

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_pct(self) -> float:
        m = self.mid
        if m <= 0:
            return float("inf")
        return (self.ask - self.bid) / m * 100.0


# =============================================================================
# Base provider
# =============================================================================

class DataProvider(ABC):
    """Abstract base for all market-data providers."""

    name: str = "abstract"

    @abstractmethod
    def is_available(self) -> bool:
        """True if the provider can be used (credentials present, etc.)."""

    @abstractmethod
    def get_daily_bars(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> pd.DataFrame:
        """Fetch daily OHLCV bars. Returns empty DataFrame if no data."""

    # ---- Optional methods with default fallbacks --------------------------

    def get_metadata(self, symbol: str) -> SymbolMetadata:
        """Return symbol metadata. Default: minimal metadata with UNKNOWN values.

        Override per provider when richer info is available.
        """
        return SymbolMetadata(symbol=self.normalize_symbol(symbol))

    def get_quote(self, symbol: str) -> Quote | None:
        """Return latest bid/ask quote. Default: None (most daily providers).

        Override in providers that have real-time quote APIs (Polygon, Alpaca).
        """
        return None

    # ---- helpers shared by all providers ---------------------------------

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        return symbol.upper().strip()

    @staticmethod
    def empty_frame() -> pd.DataFrame:
        idx = pd.DatetimeIndex([], name="date")
        return pd.DataFrame({c: pd.Series(dtype="float64") for c in OHLCV_COLUMNS}, index=idx)


# =============================================================================
# Exceptions
# =============================================================================

class ProviderError(Exception):
    """Raised when a provider fails after retries."""


class RateLimitError(ProviderError):
    """Raised when a provider's rate limit is hit and retries are exhausted."""


class SymbolNotFoundError(ProviderError):
    """Raised when a symbol is not available from the provider."""
