"""Persist last successful scan report on disk (survives new browser sessions)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
META_PATH = ROOT / "data" / "reports" / ".last_report.json"


def save_last_report(report_file: str, profile: str = "") -> None:
    name = Path(report_file).name
    if not name.endswith("_report.csv"):
        return
    path = ROOT / "data" / "reports" / name
    if not path.is_file() or path.stat().st_size == 0:
        return
    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "report_file": name,
        "profile": profile,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "size_bytes": path.stat().st_size,
    }
    META_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_last_report() -> dict:
    if not META_PATH.is_file():
        return {}
    try:
        data = json.loads(META_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    name = str(data.get("report_file", "")).strip()
    if not name:
        return {}
    path = ROOT / "data" / "reports" / name
    if not path.is_file() or path.stat().st_size == 0:
        return {}
    return data


def last_report_path() -> Path | None:
    meta = load_last_report()
    name = meta.get("report_file")
    if not name:
        return None
    path = ROOT / "data" / "reports" / str(name)
    return path if path.is_file() and path.stat().st_size > 0 else None
