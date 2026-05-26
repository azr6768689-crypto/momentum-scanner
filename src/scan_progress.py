"""Scan progress file for cloud dashboard progress bar."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

_last_disk_write = 0.0

ROOT = Path(__file__).resolve().parent.parent
PROGRESS_PATH = ROOT / "data" / "reports" / ".scan_progress.json"


def _progress_path() -> Path:
    return Path(os.getenv("SCAN_PROGRESS_PATH", str(PROGRESS_PATH)))


def write_progress(
    percent: int,
    phase: str,
    *,
    done: int = 0,
    total: int = 0,
    message: str = "",
    profile_id: str = "",
    profile_label: str = "",
    force: bool = False,
) -> None:
    path = _progress_path()
    payload = {
        "percent": max(0, min(100, int(percent))),
        "phase": phase,
        "done": int(done),
        "total": int(total),
        "message": message or phase,
        "profile_id": profile_id,
        "profile_label": profile_label,
        "updated_at": time.time(),
    }
    global _last_disk_write
    now = time.time()
    if (
        not force
        and 0 < int(percent) < 100
        and now - _last_disk_write < 1.0
    ):
        return
    _last_disk_write = now
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f"{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False))
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def read_progress() -> dict:
    path = _progress_path()
    if not path.exists():
        return {"percent": 0, "phase": "", "done": 0, "total": 0, "message": ""}
    for _ in range(3):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            time.sleep(0.05)
        except OSError:
            break
    return {"percent": 0, "phase": "", "done": 0, "total": 0, "message": ""}


def progress_last_updated() -> float | None:
    path = _progress_path()
    if not path.is_file():
        return None
    try:
        data = read_progress()
        if data.get("updated_at"):
            return float(data["updated_at"])
        return path.stat().st_mtime
    except OSError:
        return None


def clear_progress() -> None:
    path = _progress_path()
    if path.exists():
        path.unlink(missing_ok=True)
