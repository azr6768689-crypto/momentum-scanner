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
    if os.getenv("AUTO_SCAN_ON_ENTRY", "true").lower() not in {"0", "false", "no"}:
        print("AUTO_SCAN_ON_ENTRY enabled; skipping blocking startup scan.", flush=True)
        return
    if _has_report():
        print("Existing report found; skipping startup scan.", flush=True)
        return

    universe_csv = ROOT / os.getenv("SCANNER_UNIVERSE_CSV", "data/universe/polygon_liquid_us.csv")
    sector_map = ROOT / os.getenv("SCANNER_SECTOR_MAP", "data/universe/sector_map.csv")
    profile_id = os.getenv("SCAN_PROFILE", "simple")

    sys.path.insert(0, str(ROOT))
    from src.scan_profiles import get_profile

    profile = get_profile(profile_id)
    cmd = [
        sys.executable,
        "scripts/run_pro_scanner.py",
        "--profile",
        profile.id,
        "--sector-map",
        str(sector_map),
    ]
    output_suffix = os.getenv("SCANNER_OUTPUT_SUFFIX", "").strip()
    if output_suffix:
        cmd.extend(["--output-suffix", output_suffix])
    if universe_csv.exists():
        cmd.extend(["--universe-csv", str(universe_csv)])
    else:
        print(f"Universe CSV not found at {universe_csv}; using configured starter universe.", flush=True)

    print("No report found; running initial scan before starting dashboard.", flush=True)
    subprocess.run(cmd, cwd=ROOT, check=False)


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
