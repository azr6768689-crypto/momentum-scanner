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
LOG_PATH = ROOT / "data" / "reports" / ".scan_job.log"
sys.path.insert(0, str(ROOT))

from src.polygon_key_store import build_scan_process_env, ensure_polygon_key_file
from src.polygon_preflight import validate_polygon_api_key
from src.scan_profiles import apply_profile_to_env, get_profile
from src.scan_progress import write_progress


def _merge_status(patch: dict) -> None:
    existing: dict = {}
    if STATUS.is_file():
        try:
            existing = json.loads(STATUS.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
    existing.update(patch)
    STATUS.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    profile_id = sys.argv[1] if len(sys.argv) > 1 else "simple"
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    profile = get_profile(profile_id)
    _merge_status(
        {
            "state": "running",
            "profile": profile_id,
            "profile_label": profile.label_he,
            "message": f"{profile.label_he}: מאתחל…",
        }
    )
    write_progress(
        2,
        "מתחיל",
        message=f"{profile.label_he}: מאתחל סריקה…",
        profile_id=profile_id,
        profile_label=profile.label_he,
    )

    apply_profile_to_env(profile)
    key = ensure_polygon_key_file()
    if not key:
        STATUS.write_text(
            json.dumps(
                {
                    "state": "error",
                    "message": "חסר מפתח Polygon. הדבק בסרגל → שמור מפתח.",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return 1
    env, _ = build_scan_process_env(os.environ.copy())
    env["SCAN_WORKERS"] = os.getenv("SCAN_WORKERS", "2")
    env["SCAN_PROGRESS_PATH"] = str(ROOT / "data" / "reports" / ".scan_progress.json")

    ok, msg = validate_polygon_api_key(key)
    if not ok:
        _merge_status({"state": "error", "message": msg})
        print(f"error_message={msg}", flush=True)
        return 1
    write_progress(
        4,
        "מאמת מפתח",
        message=f"{profile.label_he}: מפתח תקין, טוען נתונים…",
        profile_id=profile_id,
        profile_label=profile.label_he,
    )

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
            stdout=sys.stdout,
            stderr=subprocess.STDOUT,
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

    if LOG_PATH.exists():
        try:
            out = LOG_PATH.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            out = ""
    parsed: dict[str, str] = {}
    for line in out.splitlines():
        if "=" in line:
            key, _, val = line.partition("=")
            parsed[key.strip()] = val.strip()

    err_msg = (
        parsed.get("error_message")
        or parsed.get("error")
        or ""
    ).strip()
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
            {
                "state": "error",
                "message": err_msg or "הסריקה נכשלה — בדוק מפתח Polygon או לוג בסרגל הצד.",
                "log": out[-5000:],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
