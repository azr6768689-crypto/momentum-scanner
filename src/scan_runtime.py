"""Environment setup for detached cloud scan subprocesses (provider-agnostic)."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROGRESS_PATH = ROOT / "data" / "reports" / ".scan_progress.json"

# Polygon / heavy profiles: keep low on Render Free (512MB). 8x parallel
# bulk fetches at 5+MB JSON each is enough to OOM the container, so the
# scanning thread pool is intentionally small. Crank up only when running
# on a larger Render plan.
_RENDER_MAX_WORKERS = 3
# Demo is in-process CPU only — more threads helps on multi-core hosts.
_RENDER_DEMO_MAX_WORKERS = 8


def is_render_host() -> bool:
    return os.getenv("RENDER", "").strip().lower() in {"1", "true", "yes", "on"}


def is_demo_provider() -> bool:
    return os.getenv("DATA_PROVIDER", "demo").strip().lower() == "demo"


def render_fast_mode() -> bool:
    return os.getenv("SCAN_RENDER_FAST", "").strip().lower() in {"1", "true", "yes", "on"}


_RENDER_FREE_HARD_CAP = 1500


def cloud_symbol_cap() -> int | None:
    """Universe cap on cloud.

    Honours SCAN_CLOUD_MAX_SYMBOLS (0/unset = no explicit cap) but always
    enforces a SAFE upper bound on Render Free (512MB) to prevent OOM. The
    user can lift the cap by upgrading to Render Starter+ and setting
    SCAN_RENDER_PLAN=starter (or similar) to disable the safety.
    """
    raw = os.getenv("SCAN_CLOUD_MAX_SYMBOLS", "").strip()
    explicit: int | None = None
    if raw.isdigit() and int(raw) > 0:
        explicit = int(raw)

    if not is_render_host() or not is_polygon_provider():
        return explicit

    # Render: enforce hard safety cap unless the user opted out by signalling
    # they're on a larger plan.
    plan = os.getenv("SCAN_RENDER_PLAN", "free").strip().lower()
    if plan in {"starter", "standard", "pro", "performance"}:
        return explicit

    if explicit is None or explicit > _RENDER_FREE_HARD_CAP:
        return _RENDER_FREE_HARD_CAP
    return explicit


def is_polygon_provider() -> bool:
    return os.getenv("DATA_PROVIDER", "polygon").strip().lower() == "polygon"


def cap_scan_workers(requested: int | str | None = None) -> int:
    """Keep parallelism safe on Render Free — higher for demo-only fast scans."""
    raw = str(requested if requested is not None else os.getenv("SCAN_WORKERS", "8")).strip()
    try:
        n = max(1, int(raw))
    except ValueError:
        n = 8
    if is_render_host():
        ceiling = _RENDER_DEMO_MAX_WORKERS if is_demo_provider() else _RENDER_MAX_WORKERS
        return min(n, ceiling)
    return min(n, 32)


def apply_render_fast_env() -> None:
    """Shorter history on cloud for sub-minute demo scans."""
    if not (is_render_host() and render_fast_mode()):
        return
    os.environ.setdefault("SCAN_SKIP_SPARKLINES", "true")
    os.environ.setdefault("SCAN_SKIP_WEEKLY_SPARKLINES", "true")
    os.environ.setdefault("SCAN_SKIP_BACKTEST", "true")
    if is_demo_provider():
        os.environ.setdefault("SCAN_TRIM_BARS", "63")
    else:
        os.environ.setdefault("SCAN_TRIM_BARS", "126")
        os.environ.setdefault("SCAN_POLYGON_BULK", "true")


def build_scan_subprocess_env(base: dict | None = None) -> dict:
    """Copy process env and ensure scan paths; cap workers on cloud."""
    from src.polygon_key_store import build_scan_process_env, resolve_polygon_api_key

    env = dict(base if base is not None else os.environ)
    scan_env, _key = build_scan_process_env(env)
    env = scan_env
    if resolve_polygon_api_key():
        env["DATA_PROVIDER"] = "polygon"
    else:
        env.setdefault("DATA_PROVIDER", os.getenv("DATA_PROVIDER", "polygon"))
    env.setdefault("SCAN_PROGRESS_PATH", str(PROGRESS_PATH))
    env.setdefault("RENDER", os.getenv("RENDER", ""))
    apply_render_fast_env()
    workers = cap_scan_workers(env.get("SCAN_WORKERS"))
    analyze = env.get("SCAN_ANALYZE_WORKERS", "").strip()
    if analyze.isdigit():
        analyze_n = min(int(analyze), workers)
    else:
        analyze_n = workers
    env["SCAN_WORKERS"] = str(workers)
    env["SCAN_ANALYZE_WORKERS"] = str(analyze_n)
    return env
