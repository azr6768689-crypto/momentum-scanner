"""Resolve and persist Polygon API keys (env + optional on-disk file)."""

from __future__ import annotations

import os
from pathlib import Path

from src.env_secrets import clean_env_secret

ROOT = Path(__file__).resolve().parent.parent
POLYGON_KEY_FILE = ROOT / "data" / ".polygon_key"

_INVALID_PLACEHOLDERS = frozenset({"polygon", "demo", "tiingo", ""})


def _is_cloud_runtime() -> bool:
    return bool(
        os.getenv("RENDER", "").strip().lower() == "true"
        or os.getenv("SPACE_ID")
        or os.getenv("SPACE_REPO_NAME")
    )


def normalize_polygon_key(raw: str) -> str:
    """Strip quotes, whitespace, newlines — common paste mistakes."""
    key = clean_env_secret(raw)
    return "".join(key.split())


def _key_from_env() -> str:
    for name in ("POLYGON_API_KEY", "MASSIVE_API_KEY", "POLYGON_KEY"):
        value = normalize_polygon_key(os.getenv(name, ""))
        if value and value.lower() not in _INVALID_PLACEHOLDERS and not value.startswith("hf_"):
            return value
    return ""


def _key_from_file() -> str:
    if not POLYGON_KEY_FILE.is_file():
        return ""
    value = normalize_polygon_key(POLYGON_KEY_FILE.read_text(encoding="utf-8"))
    if value and value.lower() not in _INVALID_PLACEHOLDERS:
        return value
    return ""


def polygon_key_source() -> str:
    """Where the active key comes from (for UI diagnostics)."""
    file_key = _key_from_file()
    env_key = _key_from_env()
    on_cloud = _is_cloud_runtime()
    if on_cloud and file_key:
        return "קובץ שמור באפליקציה (דורס Render Environment)"
    if env_key:
        return "Render Environment / .env"
    if file_key:
        return "קובץ שמור באפליקציה"
    return "לא הוגדר"


def resolve_polygon_api_key() -> str:
    """On cloud: saved file beats stale Render env. Locally: env then file."""
    file_key = _key_from_file()
    env_key = _key_from_env()
    if _is_cloud_runtime() and file_key:
        return file_key
    if env_key:
        return env_key
    return file_key


def save_polygon_api_key(raw_key: str) -> str:
    """Validate, persist to disk, and override process env."""
    from src.polygon_preflight import validate_polygon_api_key

    key = normalize_polygon_key(raw_key)
    if not key or key.lower() in _INVALID_PLACEHOLDERS:
        raise ValueError("מפתח ריק או לא תקין")
    ok, msg = validate_polygon_api_key(key)
    if not ok:
        raise ValueError(msg)
    POLYGON_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    POLYGON_KEY_FILE.write_text(key + "\n", encoding="utf-8")
    os.environ["POLYGON_API_KEY"] = key
    os.environ["MASSIVE_API_KEY"] = key
    return key


def clear_polygon_api_key_file() -> None:
    POLYGON_KEY_FILE.unlink(missing_ok=True)
    for name in ("POLYGON_API_KEY", "MASSIVE_API_KEY", "POLYGON_KEY"):
        os.environ.pop(name, None)


def polygon_key_tail(key: str = "") -> str:
    k = key or resolve_polygon_api_key()
    return k[-4:] if len(k) >= 4 else "????"
