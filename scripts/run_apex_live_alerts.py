#!/usr/bin/env python3
"""CLI: run live alert pass on watchlist (cron / manual)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", type=str, default="", help="Comma-separated tickers")
    parser.add_argument("--from-report", type=Path, default=None, help="Use top N from Apex CSV")
    parser.add_argument("--top", type=int, default=50)
    args = parser.parse_args()

    import pandas as pd

    from src.apex_live.live_engine import scan_live_watchlist
    from src.config import ensure_directories, load_settings
    from src.data import get_provider
    from src.polygon_key_store import apply_polygon_key_to_env

    apply_polygon_key_to_env()
    settings = load_settings()
    ensure_directories(settings)
    provider = get_provider(settings)

    daily = None
    symbols: list[str] = []
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    elif args.from_report and args.from_report.is_file():
        daily = pd.read_csv(args.from_report)
        symbols = daily.sort_values("Apex Score", ascending=False)["סימבול"].astype(str).head(args.top).tolist()
    else:
        print("Provide --symbols or --from-report")
        return 1

    snaps, events = scan_live_watchlist(symbols, provider, daily)
    print(f"live_snapshots={len(snaps)}")
    print(f"new_alerts={len(events)}")
    for ev in events[:20]:
        print(f"ALERT {ev.symbol}: {ev.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
