#!/usr/bin/env python3
"""
Daily scan runner.

Usage:
    python scripts/run_daily.py              # full universe
    python scripts/run_daily.py --limit 500  # first 500 tickers (testing)

Outputs (in data/reports/):
    YYYY-MM-DD_report.csv         - MAIN: strong candidates (score >= main_threshold)
    YYYY-MM-DD_watchlist.csv      - WATCHLIST: not trade-ready, needs confirmation
    YYYY-MM-DD_rejected.csv       - REJECTED: below watchlist threshold + reasons
    YYYY-MM-DD_summary.txt        - human-readable summary
    YYYY-MM-DD_diagnostics.txt    - rejection breakdown by reason and category

Thresholds are controlled by config/settings.yaml:
    report_mode.active: strict | balanced | exploratory
"""

from __future__ import annotations

import argparse
import sys
import time
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import load_settings
from src.pipeline import run_pipeline


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily momentum scan")
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Limit the number of tickers (useful for testing)",
    )
    args = parser.parse_args()

    t0 = time.time()

    try:
        settings = load_settings()
    except Exception as exc:
        print(f"[ERROR] Failed to load settings: {exc}", file=sys.stderr)
        return 1

    _setup_logging(settings.log_level)
    log = logging.getLogger("run_daily")
    log.info("Starting daily scan (mode=%s, limit=%s)...",
             settings.report_mode.active, args.limit or "none")

    try:
        result = run_pipeline(settings, limit=args.limit)
    except Exception as exc:
        log.exception("Pipeline failed: %s", exc)
        return 1

    elapsed = time.time() - t0
    stats = result["stats"]

    print()
    print(f"  Report mode:               {stats['report_mode']}")
    print(f"    Main report threshold:   score >= {stats['main_score_threshold']}")
    print(f"    Watchlist threshold:     score >= {stats['watchlist_score_threshold']}")
    print()
    print(f"  Total tickers scanned:     {stats['universe_size']}")
    print(f"  Passed liquidity filter:   {stats['passed_liquidity_filter']}")
    print(f"  Total raw signals:         {stats['total_signals']}")
    print()
    print(f"  main_report_count:         {stats['main_report']}")
    print(f"  watchlist_count:           {stats['watchlist']}")
    print(f"  rejected_count:            {stats['rejected']}")
    print()
    print(f"  Files written to {settings.reporting.output_dir}:")
    print(f"    📄 Main report:    {result['csv_path'].name}")
    print(f"    📄 Watchlist:      {result['watchlist_path'].name}")
    print(f"    📄 Rejected:       {result['rejected_path'].name}")
    print(f"    📄 Summary:        {result['summary_path'].name}")
    print(f"    📄 Diagnostics:    {result['diagnostics_path'].name}")
    print()
    print(f"  Elapsed: {elapsed:.1f}s")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
