"""Scan progress file for cloud dashboard progress bar."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

_last_disk_write = 0.0

ROOT = Path(__file__).resolve().parent.parent
PROGRESS_PATH = ROOT / "data" / "reports" / ".scan_progress.json"


def write_progress(
    percent: int,
    phase: str,
    *,
    done: int = 0,
    total: int = 0,
    message: str = "",
    profile_id: str = "",
    profile_label: str = "",
) -> None:
    path = os.getenv("SCAN_PROGRESS_PATH", str(PROGRESS_PATH))
    payload = {
        "percent": max(0, min(100, int(percent))),
        "phase": phase,
        "done": int(done),
        "total": int(total),
        "message": message or phase,
        "profile_id": profile_id,
        "profile_label": profile_label,
    }
    global _last_disk_write
    now = time.time()
    if 0 < int(percent) < 100 and now - _last_disk_write < 1.5:
        return
    _last_disk_write = now
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def read_progress() -> dict:
    path = Path(os.getenv("SCAN_PROGRESS_PATH", str(PROGRESS_PATH)))
    if not path.exists():
        return {"percent": 0, "phase": "", "done": 0, "total": 0, "message": ""}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"percent": 0, "phase": "", "done": 0, "total": 0, "message": ""}


def clear_progress() -> None:
    path = Path(os.getenv("SCAN_PROGRESS_PATH", str(PROGRESS_PATH)))
    if path.exists():
        path.unlink(missing_ok=True)
