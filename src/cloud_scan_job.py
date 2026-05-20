"""Cloud scan job — subprocess survives Streamlit reruns on Hugging Face."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS_PATH = ROOT / "data" / "reports" / ".scan_job.json"
PID_PATH = ROOT / "data" / "reports" / ".scan_job.pid"
LOG_PATH = ROOT / "data" / "reports" / ".scan_job.log"
RUNNER = ROOT / "scripts" / "cloud_scan_runner.py"

from src.scan_progress import clear_progress, read_progress


def _read_status() -> dict:
    if not STATUS_PATH.exists():
        return {"state": "idle"}
    try:
        data = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"state": "idle"}

    if data.get("state") == "running" and PID_PATH.exists():
        try:
            pid = int(PID_PATH.read_text().strip())
            os.kill(pid, 0)
        except (OSError, ValueError):
            data = {
                "state": "error",
                "message": "התהליך נעצר (ייתכן שהשרת איפס). לחץ שוב על הרץ סריקה.",
            }
            _write_status(data)
            PID_PATH.unlink(missing_ok=True)
    return data


def _write_status(payload: dict) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_log_progress() -> dict:
    if not LOG_PATH.exists():
        return {}
    try:
        text = LOG_PATH.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}
    matches = re.findall(
        r"Loaded (\d+)/(\d+) (?:universe stocks|symbols)",
        text,
    )
    if matches:
        done, total = matches[-1]
        return {"done": int(done), "total": int(total)}
    return {}


def get_scan_progress() -> dict:
    """Merged progress for UI: percent, phase, message."""
    job = _read_status()
    prog = read_progress()
    log_bits = _parse_log_progress()

    if job.get("state") == "ok":
        return {
            "percent": 100,
            "phase": "הושלם",
            "message": job.get("message", "דוח מוכן"),
            "done": job.get("symbols_requested", 0),
            "total": job.get("symbols_requested", 0),
        }
    if job.get("state") == "error":
        return {
            "percent": prog.get("percent", 0),
            "phase": "שגיאה",
            "message": job.get("message", "שגיאה"),
            "done": 0,
            "total": 0,
        }
    if job.get("state") != "running":
        return {"percent": 0, "phase": "", "message": "", "done": 0, "total": 0}

    percent = int(prog.get("percent", 0))
    if percent <= 0 and log_bits:
        done, total = log_bits.get("done", 0), log_bits.get("total", 1)
        percent = 5 + int(70 * done / max(total, 1))

    profile_id = job.get("profile") or prog.get("profile_id") or ""
    profile_label = prog.get("profile_label") or job.get("profile_label") or ""
    if not profile_label and profile_id:
        try:
            from src.scan_profiles import get_profile

            profile_label = get_profile(profile_id).label_he
        except Exception:
            profile_label = ""

    return {
        "percent": percent,
        "phase": prog.get("phase") or "סריקה",
        "message": prog.get("message") or job.get("message", "סריקה רצה…"),
        "done": prog.get("done") or log_bits.get("done", 0),
        "total": prog.get("total") or log_bits.get("total", 2114),
        "profile_id": profile_id,
        "profile_label": profile_label,
    }


def is_scan_running() -> bool:
    return _read_status().get("state") == "running"


def start_full_scan(profile_id: str = "simple") -> tuple[bool, str]:
    """Launch detached scan process. Returns (started, message)."""
    if is_scan_running():
        return False, "סריקה כבר רצה."

    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    clear_progress()
    if LOG_PATH.exists():
        LOG_PATH.unlink(missing_ok=True)

    log_file = open(LOG_PATH, "w", encoding="utf-8")
    env = os.environ.copy()
    from src.polygon_key_store import resolve_polygon_api_key

    polygon_key = resolve_polygon_api_key()
    if polygon_key:
        env["POLYGON_API_KEY"] = polygon_key
        env["MASSIVE_API_KEY"] = polygon_key
        env["DATA_PROVIDER"] = "polygon"
    env["SCAN_PROGRESS_PATH"] = str(ROOT / "data" / "reports" / ".scan_progress.json")
    try:
        proc = subprocess.Popen(
            [sys.executable, str(RUNNER), profile_id],
            cwd=str(ROOT),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
    except OSError as exc:
        log_file.close()
        return False, f"לא הצלחתי להפעיל סריקה: {exc}"

    from src.scan_profiles import get_profile

    profile = get_profile(profile_id)
    PID_PATH.write_text(str(proc.pid), encoding="utf-8")
    _write_status(
        {
            "state": "running",
            "profile": profile_id,
            "profile_label": profile.label_he,
            "pid": proc.pid,
            "message": f"{profile.label_he}: סריקה רצה…",
            "percent": 0,
        }
    )
    return True, "הסריקה התחילה."


def get_status() -> dict:
    status = _read_status()
    if status.get("state") == "running":
        status["progress"] = get_scan_progress()
    return status
