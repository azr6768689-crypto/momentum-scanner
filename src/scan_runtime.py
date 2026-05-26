"""Environment setup for detached cloud scan subprocesses (provider-agnostic)."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROGRESS_PATH = ROOT / "data" / "reports" / ".scan_progress.json"

_RENDER_MAX_WORKERS = 4


def is_render_host() -> bool:
    return os.getenv("RENDER", "").strip().lower() in {"1", "true", "yes", "on"}


def cap_scan_workers(requested: int | str | None = None) -> int:
    """Keep parallelism safe on Render Free (512MB) — avoids OOM freezes."""
    raw = str(requested if requested is not None else os.getenv("SCAN_WORKERS", "2")).strip()
    try:
        n = max(1, int(raw))
    except ValueError:
        n = 2
    if is_render_host():
        return min(n, _RENDER_MAX_WORKERS)
    return min(n, 32)


def build_scan_subprocess_env(base: dict | None = None) -> dict:
    """Copy process env and ensure scan paths; cap workers on cloud."""
    env = dict(base if base is not None else os.environ)
    env.setdefault("DATA_PROVIDER", os.getenv("DATA_PROVIDER", "demo"))
    env.setdefault("SCAN_PROGRESS_PATH", str(PROGRESS_PATH))
    env.setdefault("RENDER", os.getenv("RENDER", ""))
    workers = cap_scan_workers(env.get("SCAN_WORKERS"))
    analyze = env.get("SCAN_ANALYZE_WORKERS", "").strip()
    if analyze.isdigit():
        analyze_n = min(int(analyze), workers)
    else:
        analyze_n = workers
    env["SCAN_WORKERS"] = str(workers)
    env["SCAN_ANALYZE_WORKERS"] = str(analyze_n)
    return env
