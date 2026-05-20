"""Resolve and persist Polygon API keys (env + optional on-disk file)."""

from __future__ import annotations

import os
from pathlib import Path

from src.env_secrets import clean_env_secret

ROOT = Path(__file__).resolve().parent.parent
POLYGON_KEY_FILE = ROOT / "data" / ".polygon_key"

_INVALID_PLACEHOLDERS = frozenset({"polygon", "demo", "tiingo", ""})


def resolve_polygon_api_key() -> str:
    """Env vars first, then data/.polygon_key (survives Render secret typos)."""
    for name in ("POLYGON_API_KEY", "MASSIVE_API_KEY", "POLYGON_KEY"):
        value = clean_env_secret(os.getenv(name, ""))
        if value and value.lower() not in _INVALID_PLACEHOLDERS and not value.startswith("hf_"):
            return value
    if POLYGON_KEY_FILE.is_file():
        value = clean_env_secret(POLYGON_KEY_FILE.read_text(encoding="utf-8"))
        if value and value.lower() not in _INVALID_PLACEHOLDERS:
            return value
    return ""


def save_polygon_api_key(raw_key: str) -> str:
    """Persist key to disk and current process env; returns cleaned key."""
    key = clean_env_secret(raw_key)
    if not key or key.lower() in _INVALID_PLACEHOLDERS:
        raise ValueError("מפתח ריק או לא תקין")
    POLYGON_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    POLYGON_KEY_FILE.write_text(key + "\n", encoding="utf-8")
    os.environ["POLYGON_API_KEY"] = key
    return key


def polygon_key_tail(key: str = "") -> str:
    k = key or resolve_polygon_api_key()
    return k[-4:] if len(k) >= 4 else "????"
