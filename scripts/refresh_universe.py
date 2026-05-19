#!/usr/bin/env python3
"""
Refresh the US stock universe.

Downloads ALL US-listed symbols from Nasdaq Trader, classifies them
(common stock / ETF / leveraged ETF / excluded junk), and saves 5 CSV files.

Usage:
    python scripts/refresh_universe.py [--offline]

Options:
    --offline   Use synthetic data (for testing without network).

Output (in data/universe/):
    all_us_symbols.csv       - raw download (everything)
    us_common_stocks.csv     - common stocks only (NYSE, NASDAQ, AMEX)
    us_etfs.csv              - normal ETFs
    us_leveraged_etfs.csv    - leveraged/inverse ETFs (separate)
    final_universe.csv       - the list that run_daily.py will scan

Run this once, then run:
    python scripts/run_daily.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import load_settings
from src.universe import build_universe


# Colors
G = "\033[92m"; Y = "\033[93m"; C = "\033[96m"; R = "\033[91m"; B = "\033[1m"; W = "\033[0m"


def main() -> int:
    offline = "--offline" in sys.argv

    print(f"\n{B}{C}=== Refresh US Stock Universe ==={W}")
    if offline:
        print(f"  {Y}Mode: OFFLINE (synthetic data for testing){W}")
    else:
        print(f"  Mode: LIVE (downloading from Nasdaq Trader)")
    print()

    t0 = time.time()

    settings = load_settings()

    try:
        stats = build_universe(settings, offline=offline)
    except Exception as exc:
        print(f"\n  {R}ERROR: {exc}{W}")
        print(f"  {Y}Tip: use --offline to test without network{W}")
        return 1

    elapsed = time.time() - t0

    # Print results
    print(f"\n{B}{C}=== Universe Build Results ==={W}")
    print(f"  Total symbols downloaded:        {stats.get('total_downloaded', 0):>6,}")
    print(f"  Excluded — test issues:          {stats.get('excluded_test_issues', 0):>6,}")
    print(f"  Excluded — junk symbols:         {stats.get('excluded_junk_symbols', 0):>6,}")
    print(f"  Excluded — OTC/unknown exchange:  {stats.get('excluded_otc', 0):>6,}")
    print(f"  Excluded — inactive/deficient:   {stats.get('excluded_inactive', 0):>6,}")
    print()
    print(f"  {G}Common stocks:                   {stats.get('common_stocks', 0):>6,}{W}")
    print(f"  {G}ETFs (normal):                   {stats.get('etfs', 0):>6,}{W}")
    print(f"  {Y}ETFs (leveraged/inverse):        {stats.get('leveraged_etfs', 0):>6,}{W}")
    print()
    print(f"  {B}FINAL UNIVERSE:                  {stats.get('final_universe', 0):>6,}{W}")
    print()

    files = stats.get("files", {})
    for label, path in files.items():
        name = Path(path).name
        try:
            size = Path(path).stat().st_size / 1024
            print(f"  📄 {name:<30} ({size:.1f} KB)")
        except OSError:
            print(f"  📄 {name:<30} (not found)")

    print(f"\n  Elapsed: {elapsed:.1f}s")
    print()

    if stats.get("final_universe", 0) == 0:
        print(f"  {R}WARNING: final universe is empty! Check exclusion rules.{W}")
        return 1

    print(f"  {G}✓ Universe ready. Now run:{W}")
    print(f"    python scripts/run_daily.py")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
