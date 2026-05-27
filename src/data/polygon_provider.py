"""
Polygon.io data provider.

Uses adjusted daily aggregate bars for the current swing/momentum scanner.
The key is read through Settings and is never printed or logged.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Callable

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
        rate_limit_max_attempts: int | None = None,
        rate_limit_max_sleep: float = 60.0,
    ) -> None:
        if not api_key:
            raise ValueError("PolygonProvider requires a non-empty API key.")
        self._api_key = api_key
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "momentum-system/0.1",
        })
        self._cache = _ParquetCache(cache_dir, cache_ttl_hours, cache_enabled, self.name)
        self._rate_limit_max_attempts = max(1, int(rate_limit_max_attempts or retry_max_attempts))
        self._rate_limit_max_sleep = max(0.0, float(rate_limit_max_sleep))
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

    def _sleep_after_rate_limit(self, resp: requests.Response, label: str, attempt: int) -> None:
        retry_after = resp.headers.get("Retry-After")
        try:
            sleep_for = float(retry_after) if retry_after else 10.0
        except ValueError:
            sleep_for = 10.0
        if self._rate_limit_max_sleep <= 0:
            sleep_for = 0.0
        else:
            sleep_for = max(1.0, min(sleep_for, self._rate_limit_max_sleep))
        log.warning(
            "%s rate limit hit (%d/%d); sleeping %.0fs",
            label,
            attempt,
            self._rate_limit_max_attempts,
            sleep_for,
        )
        if sleep_for > 0:
            time.sleep(sleep_for)

    def _rate_limit_exhausted(self, label: str) -> RateLimitError:
        return RateLimitError(
            f"{label} remained rate limited after {self._rate_limit_max_attempts} attempts"
        )

    def load_universe_daily_bars(
        self,
        symbols: list[str],
        start: date,
        end: date,
        *,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Load many tickers via Polygon grouped daily bars (one API call per session day).

        Much faster than per-symbol range requests for full-universe scans (~150 calls
        vs thousands). Falls back to empty frames for symbols with no bars in range.
        """
        wanted = {self.normalize_symbol(s) for s in symbols if str(s).strip()}
        if not wanted:
            return {}

        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        session_days = pd.bdate_range(start=pd.Timestamp(start), end=pd.Timestamp(end))
        total_days = len(session_days)
        pause = 0.11  # ~9 req/s — under typical starter tier limits

        for idx, ts in enumerate(session_days, start=1):
            day = ts.date()
            try:
                rows = self._retry(self._fetch_grouped_day)(day)
            except SymbolNotFoundError:
                rows = []
            except Exception as exc:
                log.warning("Grouped daily fetch failed for %s: %s", day, exc)
                rows = []
            for row in rows:
                sym = str(row.get("T") or "").upper().strip()
                if sym in wanted:
                    buckets[sym].append(row)
            if on_progress is not None:
                on_progress(idx, total_days)
            if idx < total_days:
                time.sleep(pause)

        out: dict[str, pd.DataFrame] = {}
        for sym in wanted:
            rows = buckets.get(sym) or []
            if not rows:
                out[sym] = self.empty_frame()
                continue
            df = pd.DataFrame(rows)
            date_values = pd.to_datetime(df["t"], unit="ms").dt.tz_localize(None).dt.normalize()
            frame = pd.DataFrame(
                {
                    "open": df["o"].astype("float64"),
                    "high": df["h"].astype("float64"),
                    "low": df["l"].astype("float64"),
                    "close": df["c"].astype("float64"),
                    "volume": df["v"].astype("float64"),
                },
                index=pd.DatetimeIndex(date_values, name="date"),
            )
            frame = frame.sort_index()
            frame = frame[~frame.index.duplicated(keep="last")]
            mask = (frame.index >= pd.Timestamp(start)) & (frame.index <= pd.Timestamp(end))
            frame = frame.loc[mask]
            if not frame.empty:
                self._cache.write(sym, frame)
            out[sym] = frame[OHLCV_COLUMNS] if not frame.empty else self.empty_frame()
        return out

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

    def get_minute_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        *,
        multiplier: int = 5,
        timespan: str = "minute",
    ) -> pd.DataFrame:
        """Intraday aggregates (default 5-minute bars) for live session stats."""
        sym = self.normalize_symbol(symbol)
        try:
            return self._retry(self._fetch_aggregate)(sym, start, end, multiplier, timespan)
        except SymbolNotFoundError:
            return self.empty_frame()
        except Exception as exc:
            raise ProviderError(f"Polygon intraday fetch failed for {sym}: {exc}") from exc

    def get_prev_day_bar(self, symbol: str) -> dict[str, float]:
        """Previous session OHLCV via Polygon prev endpoint."""
        sym = self.normalize_symbol(symbol)
        url = f"{_POLYGON_BASE}/v2/aggs/ticker/{sym}/prev"
        params = {"adjusted": "true", "apiKey": self._api_key}
        resp = self._session.get(url, params=params, timeout=20)
        if resp.status_code != 200:
            return {}
        row = (resp.json().get("results") or [{}])[0]
        if not row:
            return {}
        return {
            "open": float(row.get("o", 0)),
            "high": float(row.get("h", 0)),
            "low": float(row.get("l", 0)),
            "close": float(row.get("c", 0)),
            "volume": float(row.get("v", 0)),
        }

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

        rate_limit_attempts = 0
        while url:
            resp = self._session.get(url, params=params, timeout=30)
            params = {}
            if resp.status_code == 429:
                rate_limit_attempts += 1
                if rate_limit_attempts >= self._rate_limit_max_attempts:
                    raise self._rate_limit_exhausted("Polygon reference")
                self._sleep_after_rate_limit(resp, "Polygon reference", rate_limit_attempts)
                continue
            if resp.status_code != 200:
                raise ProviderError(f"Polygon ticker list HTTP {resp.status_code}: {resp.text[:200]}")
            rate_limit_attempts = 0

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
        for attempt in range(1, self._rate_limit_max_attempts + 1):
            resp = self._session.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                if attempt >= self._rate_limit_max_attempts:
                    raise self._rate_limit_exhausted("Polygon details")
                self._sleep_after_rate_limit(resp, "Polygon details", attempt)
                continue
            if resp.status_code == 404:
                raise SymbolNotFoundError(sym)
            if resp.status_code != 200:
                raise ProviderError(f"Polygon ticker details HTTP {resp.status_code} for {sym}: {resp.text[:200]}")
            payload = resp.json()
            result = payload.get("results") or {}
            return result if isinstance(result, dict) else {}
        raise self._rate_limit_exhausted("Polygon details")

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
        for attempt in range(1, self._rate_limit_max_attempts + 1):
            resp = self._session.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                if attempt >= self._rate_limit_max_attempts:
                    raise self._rate_limit_exhausted("Polygon news")
                self._sleep_after_rate_limit(resp, "Polygon news", attempt)
                continue
            if resp.status_code == 404:
                return []
            if resp.status_code != 200:
                raise ProviderError(f"Polygon news HTTP {resp.status_code} for {sym}: {resp.text[:200]}")
            payload = resp.json()
            results = payload.get("results") or []
            return [item for item in results if isinstance(item, dict)]
        raise self._rate_limit_exhausted("Polygon news")

    def _fetch_grouped_day(self, day: date) -> list[dict[str, Any]]:
        url = f"{_POLYGON_BASE}/v2/aggs/grouped/locale/us/market/stocks/{day.isoformat()}"
        params = {"adjusted": "true", "apiKey": self._api_key}
        resp = self._session.get(url, params=params, timeout=60)
        if resp.status_code == 404:
            return []
        if resp.status_code == 429:
            self._sleep_after_rate_limit(resp, "Polygon grouped", 1)
            raise RateLimitError("Polygon grouped HTTP 429")
        if resp.status_code != 200:
            raise ProviderError(f"Polygon grouped HTTP {resp.status_code} for {day}: {resp.text[:200]}")
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
            self._sleep_after_rate_limit(resp, "Polygon", 1)
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
