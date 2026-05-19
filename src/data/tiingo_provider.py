"""
Tiingo data provider.

Phase 1 production provider. Fetches adjusted daily OHLCV from Tiingo,
caches to Parquet on disk, applies rate limiting and retry-with-backoff.

Why Tiingo for Phase 1:
- Clean adjusted EOD data for US equities and ETFs.
- Simple REST API, well-documented.
- Generous free tier; ~$10/month for unlimited daily history.
- Easy to swap later via the DataProvider interface.

Requires:
- TIINGO_API_KEY in .env (we never accept it as a constructor argument
  except via the Settings object, which read it from .env).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .base import (
    DataProvider,
    OHLCV_COLUMNS,
    ProviderError,
    RateLimitError,
    SymbolNotFoundError,
)


log = logging.getLogger(__name__)


# =============================================================================
# Simple rate limiter — token bucket per time window
# =============================================================================
# We avoid the external "ratelimit" package's decorator pattern because we want
# threadsafe behavior and explicit blocking. This is small enough to roll our own.

class _RateLimiter:
    """Thread-safe sliding-window rate limiter.

    Tracks request timestamps and sleeps (in the calling thread) when the
    rate would otherwise be exceeded. Phase 1 is single-threaded so this is
    mostly defensive, but it costs nothing.
    """

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self.max_requests = max_requests
        self.window = window_seconds
        self._timestamps: list[float] = []
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            cutoff = now - self.window
            # Drop expired timestamps
            self._timestamps = [t for t in self._timestamps if t > cutoff]
            if len(self._timestamps) >= self.max_requests:
                # Sleep until oldest timestamp leaves the window
                sleep_for = self._timestamps[0] + self.window - now + 0.01
                if sleep_for > 0:
                    log.debug("Rate limit hit, sleeping %.2fs", sleep_for)
                    time.sleep(sleep_for)
            self._timestamps.append(time.monotonic())


# =============================================================================
# Parquet cache
# =============================================================================

class _ParquetCache:
    """Simple per-symbol Parquet cache with TTL.

    Layout: <cache_dir>/<provider>/<SYMBOL>.parquet
    """

    def __init__(self, cache_dir: Path, ttl_hours: int, enabled: bool, provider_name: str) -> None:
        self.cache_dir = cache_dir / provider_name
        self.ttl_seconds = ttl_hours * 3600
        self.enabled = enabled
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, symbol: str) -> Path:
        return self.cache_dir / f"{symbol}.parquet"

    def read(self, symbol: str) -> pd.DataFrame | None:
        if not self.enabled:
            return None
        p = self._path(symbol)
        if not p.exists():
            return None
        # TTL check
        age = time.time() - p.stat().st_mtime
        if age > self.ttl_seconds:
            log.debug("Cache for %s is stale (%.0fs old)", symbol, age)
            return None
        try:
            df = pd.read_parquet(p)
            # Re-establish the DatetimeIndex name (Parquet roundtripping can lose it)
            df.index.name = "date"
            return df
        except Exception as exc:
            log.warning("Failed to read cache for %s: %s", symbol, exc)
            return None

    def write(self, symbol: str, df: pd.DataFrame) -> None:
        if not self.enabled or df.empty:
            return
        try:
            df.to_parquet(self._path(symbol), engine="pyarrow")
        except Exception as exc:
            log.warning("Failed to write cache for %s: %s", symbol, exc)


# =============================================================================
# Tiingo provider
# =============================================================================

_TIINGO_BASE = "https://api.tiingo.com"


class TiingoProvider(DataProvider):
    """Tiingo daily-bars provider."""

    name = "tiingo"

    def __init__(
        self,
        api_key: str,
        cache_dir: Path,
        cache_ttl_hours: int = 18,
        cache_enabled: bool = True,
        requests_per_hour: int = 800,
        requests_per_second: float = 5,
        retry_max_attempts: int = 4,
        retry_initial_backoff: float = 1.0,
        retry_max_backoff: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("TiingoProvider requires a non-empty API key.")
        self._api_key = api_key
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "momentum-system/0.1",
        })

        self._cache = _ParquetCache(cache_dir, cache_ttl_hours, cache_enabled, self.name)
        self._hour_limiter = _RateLimiter(requests_per_hour, window_seconds=3600.0)
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive.")
        if requests_per_second < 1:
            self._second_limiter = _RateLimiter(1, window_seconds=1.0 / requests_per_second)
        else:
            self._second_limiter = _RateLimiter(int(requests_per_second), window_seconds=1.0)

        # tenacity retry config (instance-level for testability)
        self._retry = retry(
            stop=stop_after_attempt(retry_max_attempts),
            wait=wait_exponential(
                multiplier=retry_initial_backoff,
                max=retry_max_backoff,
            ),
            retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout, RateLimitError)),
            reraise=True,
        )

    # ---- DataProvider contract ------------------------------------------

    def is_available(self) -> bool:
        return bool(self._api_key)

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        # Tiingo uses dot notation (BRK.B). Some sources use dash (BRK-B).
        return symbol.upper().strip().replace("-", ".")

    def get_daily_bars(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> pd.DataFrame:
        sym = self.normalize_symbol(symbol)

        # 1. Try cache
        cached = self._cache.read(sym)
        if cached is not None and not cached.empty:
            # Filter to requested range
            mask = (cached.index >= pd.Timestamp(start)) & (cached.index <= pd.Timestamp(end))
            sliced = cached.loc[mask]
            if not sliced.empty:
                log.debug("Cache hit for %s (%d rows)", sym, len(sliced))
                return sliced

        # 2. Fetch from API (with retries)
        try:
            df = self._retry(self._fetch_daily)(sym, start, end)
        except SymbolNotFoundError:
            return self.empty_frame()
        except Exception as exc:
            raise ProviderError(f"Tiingo fetch failed for {sym}: {exc}") from exc

        # 3. Cache and return
        if not df.empty:
            self._cache.write(sym, df)
        return df

    # ---- internals ------------------------------------------------------

    def get_metadata(self, symbol: str):
        """Tiingo metadata endpoint.

        Tiingo provides an endpoint at /tiingo/daily/<ticker> with name,
        exchange, and asset class. We call it lazily and cache results
        in-process. If unreachable, fall back to UNKNOWN defaults so the
        liquidity layer can still apply other filters.
        """
        from .base import (
            SymbolMetadata, EXCHANGE_NYSE, EXCHANGE_NASDAQ, EXCHANGE_AMEX,
            EXCHANGE_ARCA, EXCHANGE_UNKNOWN,
            ASSET_TYPE_COMMON, ASSET_TYPE_ETF, ASSET_TYPE_ADR, ASSET_TYPE_UNKNOWN,
        )
        sym = self.normalize_symbol(symbol)

        # Simple per-instance cache
        if not hasattr(self, "_metadata_cache"):
            self._metadata_cache: dict[str, SymbolMetadata] = {}
        if sym in self._metadata_cache:
            return self._metadata_cache[sym]

        # Default
        meta = SymbolMetadata(symbol=sym)

        try:
            self._hour_limiter.acquire()
            self._second_limiter.acquire()
            url = f"{_TIINGO_BASE}/tiingo/daily/{sym}"
            resp = self._session.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json() or {}
                exchange_raw = (data.get("exchangeCode") or "").upper()
                # Tiingo exchange codes
                exchange_map = {
                    "NYSE":   EXCHANGE_NYSE,
                    "NASDAQ": EXCHANGE_NASDAQ,
                    "NYSE ARCA": EXCHANGE_ARCA,
                    "NYSE AMERICAN": EXCHANGE_AMEX,
                    "AMEX":   EXCHANGE_AMEX,
                    "BATS":   "BATS",
                }
                exchange = exchange_map.get(exchange_raw, EXCHANGE_UNKNOWN)

                asset_type_raw = (data.get("assetType") or "").lower()
                asset_map = {
                    "stock": ASSET_TYPE_COMMON,
                    "etf":   ASSET_TYPE_ETF,
                    "mutual fund": ASSET_TYPE_UNKNOWN,
                }
                asset_type = asset_map.get(asset_type_raw, ASSET_TYPE_UNKNOWN)

                meta = SymbolMetadata(
                    symbol=sym,
                    exchange=exchange,
                    asset_type=asset_type,
                    name=data.get("name"),
                    is_active=True,
                )
        except Exception as exc:
            log.debug("Tiingo metadata fetch failed for %s: %s", sym, exc)

        self._metadata_cache[sym] = meta
        return meta

    def get_quote(self, symbol: str):
        """Tiingo IEX endpoint provides last bid/ask for some tickers.

        Not all subscription tiers have access — return None if unavailable.
        """
        return None  # Phase 2: enable with Polygon

    def _fetch_daily(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        self._hour_limiter.acquire()
        self._second_limiter.acquire()

        url = f"{_TIINGO_BASE}/tiingo/daily/{symbol}/prices"
        params = {
            "startDate": start.isoformat(),
            "endDate":   end.isoformat(),
            "format":    "json",
            "resampleFreq": "daily",
        }

        try:
            resp = self._session.get(url, params=params, timeout=30)
        except requests.Timeout as exc:
            log.warning("Tiingo timeout for %s: %s", symbol, exc)
            raise

        if resp.status_code == 404:
            log.info("Symbol not found on Tiingo: %s", symbol)
            raise SymbolNotFoundError(symbol)
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            try:
                sleep_for = float(retry_after) if retry_after else 30.0
            except ValueError:
                sleep_for = 30.0
            sleep_for = max(5.0, min(sleep_for, 120.0))
            log.warning("Tiingo rate limit hit (HTTP 429); sleeping %.0fs before retry", sleep_for)
            time.sleep(sleep_for)
            raise RateLimitError("Tiingo HTTP 429")
        if resp.status_code != 200:
            raise ProviderError(
                f"Tiingo HTTP {resp.status_code} for {symbol}: {resp.text[:200]}"
            )

        data = resp.json()
        if not data:
            return self.empty_frame()

        df = pd.DataFrame(data)
        # Tiingo returns: date, adjOpen, adjHigh, adjLow, adjClose, adjVolume, ...
        # We use the *adjusted* fields (split- and dividend-adjusted).
        col_map = {
            "adjOpen":   "open",
            "adjHigh":   "high",
            "adjLow":    "low",
            "adjClose":  "close",
            "adjVolume": "volume",
        }
        missing = [c for c in col_map if c not in df.columns]
        if missing:
            raise ProviderError(f"Tiingo response missing columns {missing} for {symbol}")

        df = df[list(col_map.keys()) + ["date"]].rename(columns=col_map)
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
        df = df.set_index("date").sort_index()

        # Ensure correct dtypes
        for c in OHLCV_COLUMNS:
            df[c] = df[c].astype("float64")

        return df[OHLCV_COLUMNS]
