"""
End-to-end test for strategies + scanners.

Runs DemoProvider on AAPL, MSFT, TSLA, NVDA, AMZN.
Builds all enabled strategies + scanners from YAML config.
Prints every signal found, or warns if no signals.

Usage:
    python scripts/test_scanners.py
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from src.config import load_settings, ensure_directories
from src.data import get_provider
from src.analytics.indicators import compute_snapshot
from src.strategies import build_strategies
from src.scanners import build_scanners


# Colors
G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; C = "\033[96m"; W = "\033[0m"


def main() -> int:
    print(f"{C}=== Scanner test suite ==={W}")

    # 1. Load config + provider
    settings = load_settings()
    ensure_directories(settings)
    provider = get_provider(settings)
    print(f"  Provider: {provider.name}")

    # 2. Build strategies
    strategies = build_strategies(settings.strategies_raw)
    print(f"  Enabled strategies: {len(strategies)}")
    for s in strategies:
        print(f"    • {s.name} (scanner: {s.scanner_mode})")

    # 3. Build scanners
    scanners = build_scanners(strategies, settings)
    print(f"  Scanners: {len(scanners)}")
    for sc in scanners:
        print(f"    • {sc.mode} ({len(sc.strategies)} strategies)")

    # 4. Fetch data
    end = date.today()
    start = end - timedelta(days=365 * 3)
    test_tickers = ["AAPL", "MSFT", "TSLA", "NVDA", "AMZN"]

    print(f"\n{C}=== Fetching data ==={W}")
    universe: dict[str, pd.DataFrame] = {}
    for sym in test_tickers:
        df = provider.get_daily_bars(sym, start, end)
        if not df.empty:
            universe[sym] = df
            snap = compute_snapshot(df)
            trend = snap.trend if snap else "?"
            price = f"${snap.close:.2f}" if snap else "?"
            print(f"  {sym}: {len(df)} bars, last={price}, trend={trend}")
        else:
            print(f"  {R}{sym}: NO DATA{W}")

    # 5. Run scanners
    print(f"\n{C}=== Running scanners ==={W}")
    all_signals: list = []
    for scanner in scanners:
        signals = scanner.scan_universe(universe)
        all_signals.extend(signals)
        if signals:
            print(f"\n  {Y}[{scanner.mode}]{W} found {len(signals)} signal(s):")
            for sig in signals:
                _print_signal(sig)
        else:
            print(f"\n  [{scanner.mode}] no signals")

    # 6. Summary
    print(f"\n{C}=== Summary ==={W}")
    print(f"  Total signals: {len(all_signals)}")
    by_status: dict[str, int] = {}
    by_scanner: dict[str, int] = {}
    for sig in all_signals:
        by_status[sig.status] = by_status.get(sig.status, 0) + 1
        by_scanner[sig.scanner_mode] = by_scanner.get(sig.scanner_mode, 0) + 1

    for status, count in sorted(by_status.items()):
        print(f"    {status}: {count}")
    for mode, count in sorted(by_scanner.items()):
        print(f"    scanner={mode}: {count}")

    # 7. Validate signal integrity
    print(f"\n{C}=== Signal integrity checks ==={W}")
    errors = 0
    for sig in all_signals:
        if sig.stop_loss >= sig.entry_trigger:
            print(f"  {R}FAIL{W} {sig.ticker} {sig.strategy_module}: stop >= entry")
            errors += 1
        if sig.target_1 <= sig.entry_trigger:
            print(f"  {R}FAIL{W} {sig.ticker} {sig.strategy_module}: target_1 <= entry")
            errors += 1
        if sig.risk_reward < 1.0:
            print(f"  {R}FAIL{W} {sig.ticker} {sig.strategy_module}: R/R < 1.0")
            errors += 1
        if not sig.reason:
            print(f"  {R}FAIL{W} {sig.ticker} {sig.strategy_module}: empty reason")
            errors += 1
        if not sig.invalidation:
            print(f"  {R}FAIL{W} {sig.ticker} {sig.strategy_module}: empty invalidation")
            errors += 1
        if not sig.wait_for:
            print(f"  {R}FAIL{W} {sig.ticker} {sig.strategy_module}: empty wait_for")
            errors += 1

    if errors:
        print(f"\n  {R}INTEGRITY ERRORS: {errors}{W}")
        return 1
    else:
        print(f"  {G}All signals pass integrity checks{W}")

    if len(all_signals) == 0:
        print(f"\n  {Y}WARNING: no signals found. Demo data may not trigger all strategies.{W}")
        print(f"  {Y}This is acceptable — the pipeline runs without crashing.{W}")

    print(f"\n{G}SCANNERS OK{W}")
    return 0


def _print_signal(sig) -> None:
    """Pretty-print a signal."""
    status_color = {
        "Watch": Y, "Trigger": G, "Wait for pullback": C,
        "Ignore": R, "Invalidated": R,
    }.get(sig.status, W)

    print(f"    {status_color}{sig.status:20s}{W}  {sig.ticker:6s}  "
          f"{sig.setup_type:30s}  score={sig.score_hint:3d}  "
          f"R/R={sig.risk_reward:.1f}")
    print(f"      Entry: ${sig.entry_trigger:.2f}  "
          f"Stop: ${sig.stop_loss:.2f}  "
          f"T1: ${sig.target_1:.2f}  "
          f"T2: ${sig.target_2:.2f}")
    print(f"      Reason: {sig.reason[:100]}...")
    print(f"      Wait for: {sig.wait_for}")
    if sig.warnings:
        for w in sig.warnings:
            print(f"      {Y}⚠ {w}{W}")


if __name__ == "__main__":
    raise SystemExit(main())
