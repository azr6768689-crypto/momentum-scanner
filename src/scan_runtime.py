"""Environment setup for detached cloud scan subprocesses (provider-agnostic)."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROGRESS_PATH = ROOT / "data" / "reports" / ".scan_progress.json"


def build_scan_subprocess_env(base: dict | None = None) -> dict:
    """Copy process env and ensure scan paths; no provider-specific key logic."""
    env = dict(base if base is not None else os.environ)
    env.setdefault("DATA_PROVIDER", os.getenv("DATA_PROVIDER", "demo"))
    env.setdefault("SCAN_PROGRESS_PATH", str(PROGRESS_PATH))
    env.setdefault("RENDER", os.getenv("RENDER", ""))
    return env
