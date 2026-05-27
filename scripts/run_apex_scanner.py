#!/usr/bin/env python3
"""Apex Momentum Scanner — institutional-grade universe scan."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.apex.data_loader import load_csv_universe, load_sector_map, load_universe_bars
from src.apex.report import write_apex_report
from src.apex.scanner import ApexScanner
from src.config import ensure_directories, load_settings
from src.data import get_provider
from src.scan_progress import clear_progress, write_progress
from src.scan_runtime import apply_render_fast_env, build_scan_subprocess_env, cap_scan_workers


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def _default_workers() -> int:
    raw = os.getenv("SCAN_WORKERS", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return cap_scan_workers(int(raw))
    return cap_scan_workers(8)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apex institutional momentum scanner")
    parser.add_argument("--universe-csv", type=Path, default=ROOT / "data/universe/polygon_liquid_us.csv")
    parser.add_argument("--sector-map", type=Path, default=ROOT / "data/universe/sector_map.csv")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--trim-bars", type=int, default=None)
    parser.add_argument("--output-suffix", type=str, default="apex")
    parser.add_argument("--min-score", type=int, default=0, help="Filter rows below this Apex Score in CSV")
    parser.add_argument("--no-charts", action="store_true")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Force demo provider (ignore Polygon key on disk)",
    )
    args = parser.parse_args()

    apply_render_fast_env()
    write_progress(1, "מתחיל", message="Apex Scanner — מאתחל…", force=True)

    from src.polygon_key_store import apply_polygon_key_to_env, resolve_polygon_api_key

    force_demo = args.demo or os.getenv("SCAN_ALLOW_DEMO", "").lower() in {"1", "true", "yes"}
    if force_demo:
        os.environ["DATA_PROVIDER"] = "demo"
        os.environ.pop("POLYGON_API_KEY", None)
    else:
        apply_polygon_key_to_env()
    if not force_demo and os.getenv("DATA_PROVIDER", "polygon").strip().lower() == "polygon":
        if not resolve_polygon_api_key():
            clear_progress()
            print("scanner_status=error")
            print("error_message=חסר POLYGON_API_KEY — הוסף מפתח ב-Render Environment או בדשבורד.")
            return 1
        skip_preflight = os.getenv("SCAN_SKIP_POLYGON_PREFLIGHT", "").strip().lower() in {
            "1", "true", "yes", "on",
        }
        if skip_preflight:
            write_progress(
                3,
                "אתחול",
                message="מדלג על אימות מפתח Polygon (SCAN_SKIP_POLYGON_PREFLIGHT=1)…",
                force=True,
            )
        else:
            write_progress(
                2,
                "אימות",
                message="בודק מפתח Polygon…",
                force=True,
            )
            from src.polygon_preflight import validate_polygon_api_key

            ok, msg = validate_polygon_api_key()
            if not ok:
                clear_progress()
                print("scanner_status=error")
                clean_msg = " ".join(str(msg).split())
                print(
                    f"error_message=מפתח Polygon לא תקין: {clean_msg} | "
                    "אפשר לעקוף את הבדיקה ב-Render Environment: "
                    "SCAN_SKIP_POLYGON_PREFLIGHT=1"
                )
                return 1
            write_progress(3, "אימות", message="מפתח Polygon אומת ✓", force=True)

    write_progress(3, "אתחול", message="טוען הגדרות וספק נתונים…", force=True)
    settings = load_settings()
    ensure_directories(settings)
    _setup_logging(settings.log_level)
    log = logging.getLogger("run_apex_scanner")

    try:
        provider = get_provider(settings)
    except RuntimeError as exc:
        log.error("%s", exc)
        clear_progress()
        print("scanner_status=error")
        print(f"error_message={exc}")
        return 1

    write_progress(4, "אתחול", message="טוען רשימת מניות…", force=True)
    tickers = load_csv_universe(args.universe_csv)
    sector_map = load_sector_map(args.sector_map)
    if args.limit:
        tickers = tickers[: args.limit]

    trim = args.trim_bars
    if trim is None:
        env_trim = os.getenv("SCAN_TRIM_BARS", "").strip()
        trim = int(env_trim) if env_trim.isdigit() else 126

    end = date.today()
    start = end - timedelta(days=max(int(trim * 1.8) + 60, 280))
    workers = args.workers or _default_workers()
    n = len(tickers)

    log.info("Apex scan: provider=%s symbols=%d workers=%d trim=%d", settings.provider, n, workers, trim)
    write_progress(
        5,
        "טעינה",
        total=n,
        message=f"Apex: מתחיל הורדת נתונים ל-{n:,} מניות ({workers} threads)…",
        force=True,
    )

    universe = load_universe_bars(
        tickers,
        provider,
        start,
        end,
        workers=workers,
        trim_bars=trim,
        universe_size=n,
        profile_label="Apex",
    )

    write_progress(72, "דירוג", total=n, message=f"Apex: מנתח {n:,} מניות")
    scanner = ApexScanner(
        universe,
        sector_map,
        include_charts=not args.no_charts and os.getenv("SCAN_SKIP_CHART_JSON", "").lower() not in {"1", "true"},
    )
    results = scanner.scan(tickers, workers=workers)

    if not results:
        clear_progress()
        print("scanner_status=error")
        if settings.provider == "polygon":
            print("error_message=אין נתונים מ-Polygon — בדוק מפתח API ומנוי Stocks.")
        else:
            print("error_message=לא נמצאו מניות עם דאטה לסריקה.")
        return 1

    if args.min_score > 0:
        results = [r for r in results if r.apex_score >= args.min_score]
        if not results:
            clear_progress()
            print("scanner_status=error")
            print("error_message=אף מניה לא עברה את סף הציון המינימלי.")
            return 1

    filename = settings.reporting.csv_filename_format.format(date=end.isoformat())
    filename = filename.replace("_report.csv", f"_{args.output_suffix}_report.csv")
    out = settings.reporting.output_dir / filename
    write_apex_report(results, out)

    top = sum(1 for r in results if r.apex_score >= 80)
    write_progress(100, "הושלם", done=n, total=n, message="Apex: הסריקה הסתיימה")

    print("scanner_status=ok")
    print("scan_engine=apex")
    print(f"provider={settings.provider}")
    print(f"symbols_requested={n}")
    print(f"symbols_scored={len(results)}")
    print(f"report_file={out.name}")
    print(f"top_apex_80_plus={top}")
    if results:
        print(f"best_symbol={results[0].ticker}")
        print(f"best_score={results[0].apex_score}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        import traceback

        traceback.print_exc()
        print("scanner_status=error")
        print(f"error={exc}")
        raise SystemExit(1) from exc
