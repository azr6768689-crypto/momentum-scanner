#!/usr/bin/env python3
"""Standalone scan process for Hugging Face (survives Streamlit reruns)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "data" / "reports" / ".scan_job.json"
sys.path.insert(0, str(ROOT))

from src.env_secrets import clean_env_secret
from src.scan_profiles import apply_profile_to_env, get_profile


def main() -> int:
    profile_id = sys.argv[1] if len(sys.argv) > 1 else "simple"
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(
        json.dumps(
            {"state": "running", "profile": profile_id, "message": "סריקה מלאה רצה…"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    profile = get_profile(profile_id)
    apply_profile_to_env(profile)
    env = os.environ.copy()
    key = clean_env_secret(os.getenv("POLYGON_API_KEY", "")) or clean_env_secret(
        os.getenv("MASSIVE_API_KEY", "")
    )
    if not key:
        STATUS.write_text(
            json.dumps(
                {
                    "state": "error",
                    "message": "חסר POLYGON_API_KEY ב-Secrets",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return 1
    env["POLYGON_API_KEY"] = key
    env["DATA_PROVIDER"] = "polygon"
    env["SCAN_WORKERS"] = os.getenv("SCAN_WORKERS", "6")
    env["SCAN_PROGRESS_PATH"] = str(ROOT / "data" / "reports" / ".scan_progress.json")

    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "run_pro_scanner.py"),
        "--universe-csv",
        str(ROOT / "data/universe/polygon_liquid_us.csv"),
        "--sector-map",
        str(ROOT / "data/universe/sector_map.csv"),
        "--profile",
        profile_id,
        "--workers",
        env["SCAN_WORKERS"],
    ]
    try:
        timeout_override = os.getenv("SCAN_TIMEOUT_SECONDS", "").strip()
        if timeout_override.isdigit():
            scan_timeout = int(timeout_override)
        else:
            scan_timeout = max(profile.timeout_seconds + 120, 3600)
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=scan_timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        STATUS.write_text(
            json.dumps(
                {
                    "state": "error",
                    "message": f"timeout אחרי {scan_timeout} שניות — נסה רמת simple או SCAN_WORKERS=2",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return 1

    out = "\n".join(p for p in [proc.stdout, proc.stderr] if p and p.strip())
    parsed: dict[str, str] = {}
    for line in out.splitlines():
        if "=" in line:
            key, _, val = line.partition("=")
            parsed[key.strip()] = val.strip()

    report = parsed.get("report_file", "")
    if proc.returncode == 0:
        requested = int(parsed.get("symbols_requested", "0") or 0)
        usable = int(parsed.get("symbols_with_usable_data", "0") or 0)
        rows = int(parsed.get("report_rows", "0") or 0)
        coverage = round(100.0 * usable / requested, 1) if requested else 0.0
        STATUS.write_text(
            json.dumps(
                {
                    "state": "ok",
                    "profile": profile_id,
                    "report_file": report,
                    "message": "הסריקה הסתיימה",
                    "symbols_requested": requested,
                    "symbols_with_usable_data": usable,
                    "report_rows": rows,
                    "coverage_pct": coverage,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return 0

    STATUS.write_text(
        json.dumps(
            {"state": "error", "message": "scan failed", "log": out[-5000:]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
