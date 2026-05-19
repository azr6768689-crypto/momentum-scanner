#!/usr/bin/env python3
"""Build a wider Polygon US stock universe with a minimum price filter."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import load_settings, ensure_directories
from src.data import get_provider


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Polygon liquid US universe")
    parser.add_argument("--min-price", type=float, default=10.0)
    parser.add_argument("--min-dollar-volume", type=float, default=10_000_000)
    parser.add_argument("--limit", type=int, default=None, help="Optional ticker limit for testing")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    settings = load_settings()
    ensure_directories(settings)
    provider = get_provider(settings)
    if not hasattr(provider, "list_us_stock_tickers"):
        raise RuntimeError("Current provider cannot list US stock tickers. Use DATA_PROVIDER=polygon.")

    tickers = provider.list_us_stock_tickers(limit=args.limit)
    logging.info("Reference universe: %d active US common stocks", len(tickers))

    start = date.today() - timedelta(days=90)
    end = date.today()
    rows = []
    for idx, ticker in enumerate(tickers, start=1):
        try:
            df = provider.get_daily_bars(ticker, start, end)
        except Exception as exc:
            logging.warning("Skip %s: %s", ticker, exc)
            continue
        if df.empty or len(df) < 20:
            continue
        last_close = float(df["close"].iloc[-1])
        avg_dollar_volume = float((df["close"] * df["volume"]).tail(20).mean())
        if last_close >= args.min_price and avg_dollar_volume >= args.min_dollar_volume:
            rows.append({
                "symbol": ticker,
                "last_close": round(last_close, 2),
                "avg_dollar_volume_20d": round(avg_dollar_volume, 0),
            })
        if idx % 100 == 0:
            logging.info("Checked %d/%d, kept %d", idx, len(tickers), len(rows))

    out = settings.data.cache_dir.parent / "universe" / "polygon_liquid_us.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).sort_values("avg_dollar_volume_20d", ascending=False).to_csv(out, index=False)
    print("polygon_universe_status=ok")
    print(f"checked={len(tickers)}")
    print(f"kept={len(rows)}")
    print(f"file={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
