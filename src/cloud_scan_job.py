"""Cloud scan job — subprocess survives Streamlit reruns on Hugging Face."""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS_PATH = ROOT / "data" / "reports" / ".scan_job.json"
PID_PATH = ROOT / "data" / "reports" / ".scan_job.pid"
LOG_PATH = ROOT / "data" / "reports" / ".scan_job.log"
RUNNER = ROOT / "scripts" / "cloud_scan_runner.py"

from src.scan_progress import clear_progress, read_progress, write_progress

_STALE_ZERO_PROGRESS_SEC = 300


def _tail_log(max_chars: int = 1200) -> str:
    if not LOG_PATH.exists():
        return ""
    try:
        text = LOG_PATH.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    return text[-max_chars:].strip()


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
        else:
            prog = read_progress()
            pct = int(prog.get("percent", 0) or 0)
            if pct <= 0 and STATUS_PATH.exists():
                age = time.time() - STATUS_PATH.stat().st_mtime
                if age > _STALE_ZERO_PROGRESS_SEC and not _parse_log_progress():
                    data = {
                        "state": "error",
                        "message": (
                            "הסריקה תקועה יותר מ-5 דקות ב-0%. "
                            "לחץ «בטל סריקה» ואז «סריקה» שוב. "
                            "ב-Render: SCAN_WORKERS=2."
                        ),
                        "log_tail": _tail_log(800),
                    }
                    _write_status(data)
                    PID_PATH.unlink(missing_ok=True)
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except OSError:
                        pass
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

    done = int(prog.get("done") or log_bits.get("done", 0) or 0)
    total = int(prog.get("total") or log_bits.get("total", 0) or 2114)
    message = prog.get("message") or job.get("message", "סריקה רצה…")
    if done > 0 and total > 0 and "נטענו" not in str(message):
        message = f"{message} · {done:,}/{total:,}"

    return {
        "percent": percent,
        "phase": prog.get("phase") or "סריקה",
        "message": message,
        "done": done,
        "total": total,
        "profile_id": profile_id,
        "profile_label": profile_label,
        "log_tail": _tail_log(400) if percent <= 5 else "",
    }


def is_scan_running() -> bool:
    return _read_status().get("state") == "running"


def cancel_scan() -> None:
    """Stop a stuck cloud scan and reset status."""
    if PID_PATH.exists():
        try:
            pid = int(PID_PATH.read_text().strip())
            os.kill(pid, signal.SIGTERM)
        except (OSError, ValueError):
            pass
        PID_PATH.unlink(missing_ok=True)
    clear_progress()
    _write_status({"state": "idle", "message": "הסריקה בוטלה"})
    if LOG_PATH.exists():
        LOG_PATH.unlink(missing_ok=True)


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
    write_progress(
        1,
        "מתחיל",
        message=f"{profile.label_he}: מפעיל תהליך סריקה…",
        profile_id=profile_id,
        profile_label=profile.label_he,
    )
    _write_status(
        {
            "state": "running",
            "profile": profile_id,
            "profile_label": profile.label_he,
            "pid": proc.pid,
            "message": f"{profile.label_he}: סריקה רצה…",
            "percent": 1,
            "started_at": time.time(),
        }
    )
    return True, "הסריקה התחילה."


def get_status() -> dict:
    status = _read_status()
    if status.get("state") == "running":
        status["progress"] = get_scan_progress()
    return status
