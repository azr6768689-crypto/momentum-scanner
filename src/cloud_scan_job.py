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
LAST_ATTEMPT_PATH = ROOT / "data" / "reports" / ".scan_last_attempt"
RUNNER = ROOT / "scripts" / "cloud_scan_runner.py"

from src.report_persistence import load_last_report, save_last_report
from src.scan_progress import clear_progress, progress_last_updated, read_progress, write_progress

_STALE_PROGRESS_SEC = 480
_STARTUP_GRACE_SEC = 120


def _kill_pid_tree(pid: int) -> None:
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def _tail_log(max_chars: int = 1200) -> str:
    if not LOG_PATH.exists():
        return ""
    try:
        text = LOG_PATH.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    return text[-max_chars:].strip()


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


def _maybe_recover_stale_running(data: dict, pid: int) -> dict | None:
    """Kill scan if progress file has not moved for a long time."""
    started_at = float(data.get("started_at") or 0)
    if started_at and time.time() - started_at < _STARTUP_GRACE_SEC:
        return None

    last_at = progress_last_updated()
    if last_at is None:
        age = time.time() - STATUS_PATH.stat().st_mtime if STATUS_PATH.exists() else 0
    else:
        age = time.time() - last_at

    if age <= _STALE_PROGRESS_SEC:
        return None

    prog = read_progress()
    pct = int(prog.get("percent", 0) or 0)
    _kill_pid_tree(pid)
    PID_PATH.unlink(missing_ok=True)
    return {
        "state": "error",
        "message": (
            f"הסריקה תקועה יותר מ-{int(_STALE_PROGRESS_SEC // 60)} דקות "
            f"(אחרון {pct}%). לחץ ▶ הרץ שוב. "
            "ב-Render: השאר SCAN_PROFILE=simple ו-DATA_PROVIDER=demo."
        ),
        "log_tail": _tail_log(800),
    }


def _read_status() -> dict:
    if not STATUS_PATH.exists():
        return {"state": "idle"}
    try:
        data = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"state": "idle"}

    state = str(data.get("state", "idle"))

    if state == "running" and PID_PATH.exists():
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
            stale = _maybe_recover_stale_running(data, pid)
            if stale:
                _write_status(stale)
                data = stale
    elif state == "ok" and data.get("report_file"):
        save_last_report(str(data["report_file"]), str(data.get("profile", "")))
    elif state in ("error", "idle"):
        saved = load_last_report()
        if saved.get("report_file"):
            report_name = str(saved["report_file"])
            report_path = STATUS_PATH.parent / report_name
            if report_path.is_file() and report_path.stat().st_size > 0:
                data = {
                    "state": "ok",
                    "profile": saved.get("profile", ""),
                    "report_file": report_name,
                    "message": "דוח מהסריקה האחרונה (שמור)",
                }
                _write_status(data)
    return data


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
    """Stop a running scan (process group) and mark cancelled."""
    if PID_PATH.exists():
        try:
            pid = int(PID_PATH.read_text().strip())
            _kill_pid_tree(pid)
        except (OSError, ValueError):
            pass
        PID_PATH.unlink(missing_ok=True)
    clear_progress()
    _write_status({"state": "cancelled", "message": "הסריקה בוטלה"})
    if LOG_PATH.exists():
        LOG_PATH.unlink(missing_ok=True)


def start_full_scan(profile_id: str = "simple") -> tuple[bool, str]:
    """Launch detached scan process. Returns (started, message)."""
    status = _read_status()
    if status.get("state") == "running":
        return False, "סריקה כבר רצה."

    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    clear_progress()
    if LOG_PATH.exists():
        LOG_PATH.unlink(missing_ok=True)

    from src.scan_runtime import build_scan_subprocess_env

    env = build_scan_subprocess_env(os.environ.copy())
    log_file = open(LOG_PATH, "w", encoding="utf-8")
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
    finally:
        log_file.close()

    from src.scan_profiles import get_profile

    profile = get_profile(profile_id)
    PID_PATH.write_text(str(proc.pid), encoding="utf-8")
    try:
        LAST_ATTEMPT_PATH.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass
    write_progress(
        1,
        "מתחיל",
        message=f"{profile.label_he}: מפעיל תהליך סריקה…",
        profile_id=profile_id,
        profile_label=profile.label_he,
        force=True,
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


# ---------------------------------------------------------------------------
# Auto-recurring scan helpers
# ---------------------------------------------------------------------------


def _auto_interval_hours_env() -> float:
    raw = os.getenv("SCAN_AUTO_INTERVAL_HOURS", "3").strip()
    try:
        val = float(raw)
    except ValueError:
        return 3.0
    return max(0.0, val)


def _last_report_finished_at() -> float | None:
    """Most recent successful report mtime (used as 'last scan' anchor)."""
    reports_dir = STATUS_PATH.parent
    if not reports_dir.exists():
        return None
    candidates = []
    for path in reports_dir.glob("*_report.csv"):
        try:
            candidates.append(path.stat().st_mtime)
        except OSError:
            continue
    if not candidates:
        return None
    return max(candidates)


def _read_last_attempt_at() -> float | None:
    """Timestamp persisted by start_full_scan on every attempt (success or fail)."""
    if not LAST_ATTEMPT_PATH.is_file():
        return None
    try:
        return float(LAST_ATTEMPT_PATH.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        try:
            return LAST_ATTEMPT_PATH.stat().st_mtime
        except OSError:
            return None


def last_scan_started_at() -> float | None:
    """Timestamp of the last scan attempt (running, finished, or failed).

    Uses (in priority order):
      1. status['started_at'] of the currently-running scan,
      2. the persisted .scan_last_attempt timestamp from any prior start,
      3. the mtime of the most recent successful report.

    This prevents tight retry loops after failed scans: even a failed attempt
    advances the auto-recurring clock so we wait the configured interval
    before trying again.
    """
    status = _read_status()
    started = status.get("started_at")
    if started:
        try:
            return float(started)
        except (TypeError, ValueError):
            pass
    persisted = _read_last_attempt_at()
    if persisted is not None:
        return persisted
    return _last_report_finished_at()


def seconds_until_next_auto_scan(interval_hours: float | None = None) -> float:
    """How many seconds until the next auto-scan should fire (0 = now)."""
    if interval_hours is None:
        interval_hours = _auto_interval_hours_env()
    if interval_hours <= 0:
        return float("inf")
    anchor = last_scan_started_at()
    if anchor is None:
        return 0.0
    elapsed = time.time() - anchor
    remaining = interval_hours * 3600.0 - elapsed
    return max(0.0, remaining)


def should_auto_run_scan(interval_hours: float | None = None) -> bool:
    """Return True if auto-recurring scan should be triggered now."""
    if interval_hours is None:
        interval_hours = _auto_interval_hours_env()
    if interval_hours <= 0:
        return False
    if is_scan_running():
        return False
    return seconds_until_next_auto_scan(interval_hours) <= 0


def maybe_auto_run_scan(
    profile_id: str = "simple",
    interval_hours: float | None = None,
) -> tuple[bool, str]:
    """If interval elapsed and nothing running, kick off a fresh scan."""
    if not should_auto_run_scan(interval_hours):
        return False, ""
    return start_full_scan(profile_id)
