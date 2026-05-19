"""
Polygon.io data provider.

Uses adjusted daily aggregate bars for the current swing/momentum scanner.
The key is read through Settings and is never printed or logged.
"""

from __future__ import annotations

import logging
import time
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .base import DataProvider, OHLCV_COLUMNS, ProviderError, RateLimitError, SymbolNotFoundError


log = logging.getLogger(__name__)

_POLYGON_BASE = "https://api.polygon.io"


class _ParquetCache:
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
        path = self._path(symbol)
        if not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if age > self.ttl_seconds:
            return None
        try:
            df = pd.read_parquet(path)
            df.index.name = "date"
            return df
        except Exception as exc:
            log.warning("Failed to read Polygon cache for %s: %s", symbol, exc)
            return None

    def write(self, symbol: str, df: pd.DataFrame) -> None:
        if not self.enabled or df.empty:
            return
        try:
            df.to_parquet(self._path(symbol), engine="pyarrow")
        except Exception as exc:
            log.warning("Failed to write Polygon cache for %s: %s", symbol, exc)


class PolygonProvider(DataProvider):
    name = "polygon"

    def __init__(
        self,
        api_key: str,
        cache_dir: Path,
        cache_ttl_hours: int = 18,
        cache_enabled: bool = True,
        retry_max_attempts: int = 4,
        retry_initial_backoff: float = 1.0,
        retry_max_backoff: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("PolygonProvider requires a non-empty API key.")
        self._api_key = api_key
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "momentum-system/0.1",
        })
        self._cache = _ParquetCache(cache_dir, cache_ttl_hours, cache_enabled, self.name)
        self._retry = retry(
            stop=stop_after_attempt(retry_max_attempts),
            wait=wait_exponential(multiplier=retry_initial_backoff, max=retry_max_backoff),
            retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout, RateLimitError)),
            reraise=True,
        )

    def is_available(self) -> bool:
        return bool(self._api_key)

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        return symbol.upper().strip().replace(".", "-")

    def get_daily_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        sym = self.normalize_symbol(symbol)

        cached = self._cache.read(sym)
        if cached is not None and not cached.empty:
            mask = (cached.index >= pd.Timestamp(start)) & (cached.index <= pd.Timestamp(end))
            sliced = cached.loc[mask]
            covers_start = cached.index.min() <= pd.Timestamp(start) + pd.Timedelta(days=5)
            covers_end = cached.index.max() >= pd.Timestamp(end) - pd.Timedelta(days=5)
            if not sliced.empty and covers_start and covers_end:
                return sliced

        try:
            df = self._retry(self._fetch_daily)(sym, start, end)
        except SymbolNotFoundError:
            return self.empty_frame()
        except Exception as exc:
            raise ProviderError(f"Polygon fetch failed for {sym}: {exc}") from exc

        if not df.empty:
            self._cache.write(sym, df)
        return df

    def get_hourly_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Fetch adjusted hourly aggregate bars for top-candidate chart previews."""
        sym = self.normalize_symbol(symbol)
        try:
            return self._retry(self._fetch_aggregate)(sym, start, end, 1, "hour")
        except SymbolNotFoundError:
            return self.empty_frame()
        except Exception as exc:
            raise ProviderError(f"Polygon hourly fetch failed for {sym}: {exc}") from exc

    def list_us_stock_tickers(self, limit: int | None = None) -> list[str]:
        """List active US common-stock tickers from Polygon reference data."""
        tickers: list[str] = []
        url = f"{_POLYGON_BASE}/v3/reference/tickers"
        params: dict[str, Any] = {
            "market": "stocks",
            "active": "true",
            "type": "CS",
            "locale": "us",
            "limit": 1000,
            "apiKey": self._api_key,
        }

        while url:
            resp = self._session.get(url, params=params, timeout=30)
            params = {}
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                try:
                    sleep_for = float(retry_after) if retry_after else 10.0
                except ValueError:
                    sleep_for = 10.0
                log.warning("Polygon reference rate limit hit; sleeping %.0fs", sleep_for)
                time.sleep(max(1.0, min(sleep_for, 60.0)))
                continue
            if resp.status_code != 200:
                raise ProviderError(f"Polygon ticker list HTTP {resp.status_code}: {resp.text[:200]}")

            payload = resp.json()
            for item in payload.get("results") or []:
                ticker = str(item.get("ticker") or "").upper().strip()
                if ticker:
                    tickers.append(ticker)
                    if limit is not None and len(tickers) >= limit:
                        return tickers

            next_url = payload.get("next_url")
            if next_url:
                separator = "&" if "?" in next_url else "?"
                url = f"{next_url}{separator}apiKey={self._api_key}"
            else:
                url = ""

        return tickers

    def get_ticker_details(self, symbol: str) -> dict[str, Any]:
        """Fetch reference details for one ticker without exposing the API key."""
        sym = self.normalize_symbol(symbol)
        url = f"{_POLYGON_BASE}/v3/reference/tickers/{sym}"
        params = {"apiKey": self._api_key}
        while True:
            resp = self._session.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                try:
                    sleep_for = float(retry_after) if retry_after else 10.0
                except ValueError:
                    sleep_for = 10.0
                log.warning("Polygon details rate limit hit; sleeping %.0fs", sleep_for)
                time.sleep(max(1.0, min(sleep_for, 60.0)))
                continue
            if resp.status_code == 404:
                raise SymbolNotFoundError(sym)
            if resp.status_code != 200:
                raise ProviderError(f"Polygon ticker details HTTP {resp.status_code} for {sym}: {resp.text[:200]}")
            payload = resp.json()
            result = payload.get("results") or {}
            return result if isinstance(result, dict) else {}

    def get_ticker_news(self, symbol: str, limit: int = 5) -> list[dict[str, Any]]:
        """Fetch recent Polygon news items for one ticker."""
        sym = self.normalize_symbol(symbol)
        url = f"{_POLYGON_BASE}/v2/reference/news"
        params: dict[str, Any] = {
            "ticker": sym,
            "limit": max(1, min(int(limit), 10)),
            "order": "desc",
            "sort": "published_utc",
            "apiKey": self._api_key,
        }
        while True:
            resp = self._session.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                try:
                    sleep_for = float(retry_after) if retry_after else 10.0
                except ValueError:
                    sleep_for = 10.0
                log.warning("Polygon news rate limit hit; sleeping %.0fs", sleep_for)
                time.sleep(max(1.0, min(sleep_for, 60.0)))
                continue
            if resp.status_code == 404:
                return []
            if resp.status_code != 200:
                raise ProviderError(f"Polygon news HTTP {resp.status_code} for {sym}: {resp.text[:200]}")
            payload = resp.json()
            results = payload.get("results") or []
            return [item for item in results if isinstance(item, dict)]

    def _fetch_daily(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        return self._fetch_aggregate(symbol, start, end, 1, "day")

    def _fetch_aggregate(
        self,
        symbol: str,
        start: date,
        end: date,
        multiplier: int,
        timespan: str,
    ) -> pd.DataFrame:
        url = f"{_POLYGON_BASE}/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}/{start.isoformat()}/{end.isoformat()}"
        params = {
            "adjusted": "true",
            "sort": "asc",
            "limit": 50000,
            "apiKey": self._api_key,
        }

        resp = self._session.get(url, params=params, timeout=30)
        if resp.status_code == 404:
            raise SymbolNotFoundError(symbol)
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            try:
                sleep_for = float(retry_after) if retry_after else 10.0
            except ValueError:
                sleep_for = 10.0
            log.warning("Polygon rate limit hit (HTTP 429); sleeping %.0fs before retry", sleep_for)
            time.sleep(max(1.0, min(sleep_for, 60.0)))
            raise RateLimitError("Polygon HTTP 429")
        if resp.status_code != 200:
            raise ProviderError(f"Polygon HTTP {resp.status_code} for {symbol}: {resp.text[:200]}")

        payload = resp.json()
        results = payload.get("results") or []
        if not results:
            return self.empty_frame()

        df = pd.DataFrame(results)
        required = {"t", "o", "h", "l", "c", "v"}
        missing = required - set(df.columns)
        if missing:
            raise ProviderError(f"Polygon response missing columns {sorted(missing)} for {symbol}")

        date_values = pd.to_datetime(df["t"], unit="ms").dt.tz_localize(None)
        if timespan == "day":
            date_values = date_values.dt.normalize()

        out = pd.DataFrame({
            "date": date_values,
            "open": df["o"].astype("float64"),
            "high": df["h"].astype("float64"),
            "low": df["l"].astype("float64"),
            "close": df["c"].astype("float64"),
            "volume": df["v"].astype("float64"),
        })
        out = out.set_index("date").sort_index()
        return out[OHLCV_COLUMNS]
