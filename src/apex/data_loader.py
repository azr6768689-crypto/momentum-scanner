"""Universe data loading for Apex scanner (reuses provider layer)."""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.base import ProviderError
from src.scan_progress import write_progress
from src.scan_runtime import cap_scan_workers

log = logging.getLogger(__name__)


def load_csv_universe(path: Path) -> list[str]:
    df = pd.read_csv(path)
    col = "symbol" if "symbol" in df.columns else df.columns[0]
    tickers = [str(t).upper().strip() for t in df[col].dropna()]
    seen: set[str] = set()
    return [t for t in tickers if t and not (t in seen or seen.add(t))]


def load_sector_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    if not {"symbol", "sector"}.issubset(df.columns):
        return {}
    return {
        str(r["symbol"]).upper().strip(): str(r["sector"]).strip()
        for _, r in df.dropna(subset=["symbol"]).iterrows()
        if str(r["symbol"]).strip()
    }


def _polygon_bulk_enabled(provider) -> bool:
    if not hasattr(provider, "load_universe_daily_bars"):
        return False
    return os.getenv("SCAN_POLYGON_BULK", "true").strip().lower() not in {"0", "false", "no", "off"}


def _fetch_one(ticker: str, provider, start: date, end: date, trim_bars: int | None):
    try:
        df = provider.get_daily_bars(ticker, start, end)
    except ProviderError as exc:
        msg = str(exc)
        if "401" in msg or "Unknown API Key" in msg:
            raise RuntimeError(
                "מפתח Polygon לא תקין (401). עדכן POLYGON_API_KEY ב-Render או בדשבורד."
            ) from exc
        return ticker, None
    except Exception:
        return ticker, None
    if df is None or df.empty:
        return ticker, None
    if trim_bars and len(df) > trim_bars:
        df = df.tail(trim_bars).copy()
    return ticker, df


def load_universe_bars(
    tickers: list[str],
    provider,
    start: date,
    end: date,
    *,
    workers: int,
    trim_bars: int | None,
    universe_size: int,
    profile_label: str = "Apex",
) -> dict[str, pd.DataFrame]:
    fetch = list(tickers)
    for b in ("SPY", "QQQ", "IWM"):
        if b not in fetch:
            fetch.append(b)

    universe: dict[str, pd.DataFrame] = {}

    if _polygon_bulk_enabled(provider) and len(fetch) >= 80:
        try:
            total_days = len(pd.bdate_range(start=pd.Timestamp(start), end=pd.Timestamp(end)))

            def on_day(done: int, total: int) -> None:
                pct = 5 + int(65 * done / max(total, 1))
                write_progress(
                    pct,
                    "טעינה",
                    done=min(universe_size, int(universe_size * done / max(total, 1))),
                    total=universe_size,
                    message=f"{profile_label}: Polygon {done}/{total} ימים",
                )

            raw = provider.load_universe_daily_bars(fetch, start, end, on_progress=on_day)
            for t in fetch:
                df = raw.get(t.upper().strip())
                if df is not None and not df.empty:
                    if trim_bars and len(df) > trim_bars:
                        df = df.tail(trim_bars).copy()
                    universe[t] = df
            log.info("Bulk load: %d/%d symbols", len(universe), len(fetch))
            return universe
        except Exception as exc:
            log.warning("Bulk load failed: %s", exc)

    workers = cap_scan_workers(workers)
    total = len(fetch)
    done = 0
    timeout = int(os.getenv("SCAN_SYMBOL_TIMEOUT", "90") or "90")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fetch_one, t, provider, start, end, trim_bars): t for t in fetch
        }
        for fut in as_completed(futures):
            done += 1
            try:
                ticker, df = fut.result(timeout=timeout)
            except Exception:
                continue
            if df is not None:
                universe[ticker] = df
            if done == 1 or done % 100 == 0 or done == total:
                pct = 5 + int(65 * min(done, universe_size) / max(universe_size, 1))
                write_progress(
                    pct,
                    "טעינה",
                    done=min(done, universe_size),
                    total=universe_size,
                    message=f"{profile_label}: {min(done, universe_size):,}/{universe_size:,}",
                )
    return universe
