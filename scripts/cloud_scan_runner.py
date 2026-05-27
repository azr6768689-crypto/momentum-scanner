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

from src.report_persistence import save_last_report
from src.scan_profiles import apply_profile_to_env, get_profile
from src.scan_progress import write_progress
from src.scan_runtime import (
    apply_render_fast_env,
    build_scan_subprocess_env,
    cap_scan_workers,
    cloud_symbol_cap,
    is_render_host,
)


def _merge_status(patch: dict) -> None:
    existing: dict = {}
    if STATUS.is_file():
        try:
            existing = json.loads(STATUS.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
    existing.update(patch)
    STATUS.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_scan_output(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, _, val = line.partition("=")
            parsed[key.strip()] = val.strip()
    return parsed


def _scan_timeout_seconds(profile) -> int:
    override = os.getenv("SCAN_TIMEOUT_SECONDS", "").strip()
    if override.isdigit():
        return int(override)
    base = profile.timeout_seconds + 180
    if is_render_host():
        return min(base, 1200)
    return max(base, 600)


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
        force=True,
    )

    apply_profile_to_env(profile)
    apply_render_fast_env()
    env = build_scan_subprocess_env(os.environ.copy())
    workers = cap_scan_workers(env.get("SCAN_WORKERS"))
    env["SCAN_WORKERS"] = str(workers)
    # Honour SCAN_ANALYZE_WORKERS if set (used to lower analyze concurrency
    # without lowering data-load concurrency). Default to the data workers.
    analyze_raw = env.get("SCAN_ANALYZE_WORKERS", "").strip()
    if analyze_raw.isdigit() and int(analyze_raw) > 0:
        analyze_workers = max(1, min(int(analyze_raw), workers))
    else:
        analyze_workers = workers
    env["SCAN_ANALYZE_WORKERS"] = str(analyze_workers)
    write_progress(
        4,
        "מתחיל",
        message=f"{profile.label_he}: טוען נתונים ({env.get('DATA_PROVIDER', 'demo')}, {workers} workers)…",
        profile_id=profile_id,
        profile_label=profile.label_he,
    )

    apex_mode = os.getenv("SCAN_ENGINE", "apex").strip().lower() != "legacy"
    if apex_mode:
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "run_apex_scanner.py"),
            "--universe-csv",
            str(ROOT / "data/universe/polygon_liquid_us.csv"),
            "--sector-map",
            str(ROOT / "data/universe/sector_map.csv"),
            "--output-suffix",
            "apex",
            "--no-charts",
            "--workers",
            str(workers),
            "--analyze-workers",
            str(analyze_workers),
        ]
    else:
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
            str(workers),
        ]
    cap = cloud_symbol_cap()
    if cap:
        cmd.extend(["--limit", str(cap)])
    scan_timeout = _scan_timeout_seconds(profile)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=scan_timeout,
            env=env,
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        combined = stdout + ("\n" + stderr if stderr else "")
        LOG_PATH.write_text(combined, encoding="utf-8")
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or "") + ("\n" + (exc.stderr or "") if exc.stderr else "")
        if partial:
            LOG_PATH.write_text(partial, encoding="utf-8")
        STATUS.write_text(
            json.dumps(
                {
                    "state": "error",
                    "message": (
                        f"timeout אחרי {scan_timeout} שניות — "
                        "השאר רמת simple ו-SCAN_WORKERS=2"
                    ),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return 1

    parsed = _parse_scan_output(stdout)
    err_msg = (parsed.get("error_message") or parsed.get("error") or "").strip()
    report = parsed.get("report_file", "")
    report_path = STATUS.parent / report if report else None

    if proc.returncode == 0 and report and report_path and report_path.is_file():
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
        save_last_report(report, profile_id)
        write_progress(
            100,
            "הושלם",
            message=f"{profile.label_he}: הסריקה הסתיימה",
            profile_id=profile_id,
            profile_label=profile.label_he,
            force=True,
        )
        return 0

    if proc.returncode == 0 and not report:
        err_msg = err_msg or "הסריקה הסתיימה בלי קובץ דוח — נסה שוב."

    log_tail = ""
    if LOG_PATH.exists():
        try:
            log_tail = LOG_PATH.read_text(encoding="utf-8", errors="ignore")[-5000:]
        except OSError:
            pass

    STATUS.write_text(
        json.dumps(
            {
                "state": "error",
                "message": err_msg or "הסריקה נכשלה — בדוק לוג בסרגל הצד.",
                "log": log_tail,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return proc.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
