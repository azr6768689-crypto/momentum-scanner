#!/usr/bin/env python3
"""Render entrypoint: optionally generate a report, then start Streamlit."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _has_report() -> bool:
    reports_dir = ROOT / "data" / "reports"
    return reports_dir.exists() and any(reports_dir.glob("*_report.csv"))


def _run_initial_scan() -> None:
    if os.getenv("RUN_SCAN_ON_STARTUP", "true").lower() in {"0", "false", "no"}:
        return
    if _has_report():
        print("Existing report found; skipping startup scan.", flush=True)
        return

    universe_csv = ROOT / os.getenv("SCANNER_UNIVERSE_CSV", "data/universe/polygon_liquid_us.csv")
    sector_map = ROOT / os.getenv("SCANNER_SECTOR_MAP", "data/universe/sector_map.csv")
    intraday_top = os.getenv("SCANNER_INTRADAY_TOP", "50")
    news_top = os.getenv("SCANNER_NEWS_TOP", "100")
    output_suffix = os.getenv("SCANNER_OUTPUT_SUFFIX", "full_us_10")

    cmd = [
        sys.executable,
        "scripts/run_pro_scanner.py",
        "--sector-map",
        str(sector_map),
        "--intraday-top",
        intraday_top,
        "--news-top",
        news_top,
        "--output-suffix",
        output_suffix,
    ]
    if universe_csv.exists():
        cmd[2:2] = ["--universe-csv", str(universe_csv)]
    else:
        print(f"Universe CSV not found at {universe_csv}; using configured starter universe.", flush=True)

    print("No report found; running initial scan before starting dashboard.", flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def _start_streamlit() -> None:
    port = os.getenv("PORT", "8501")
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "dashboard/app.py",
        "--server.port",
        port,
        "--server.address",
        "0.0.0.0",
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]
    os.execvp(cmd[0], cmd)


def main() -> None:
    for path in ["data/reports", "data/cache", "data/universe", "logs"]:
        (ROOT / path).mkdir(parents=True, exist_ok=True)
    _run_initial_scan()
    _start_streamlit()


if __name__ == "__main__":
    main()
