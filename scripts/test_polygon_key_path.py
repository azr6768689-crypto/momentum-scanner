#!/usr/bin/env python3
"""Regression: scan subprocess must resolve Polygon key (not empty preflight)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import load_settings
from src.polygon_key_store import build_scan_process_env, ensure_polygon_key_file
from src.polygon_preflight import validate_polygon_api_key


def main() -> int:
    os.environ["POLYGON_API_KEY"] = "test_scan_path_key_abcdefghijklmnopqrst"
    os.environ["DATA_PROVIDER"] = "polygon"
    key = ensure_polygon_key_file()
    if not key:
        print("FAIL: ensure_polygon_key_file empty")
        return 1
    env, ek = build_scan_process_env({})
    if not ek or env.get("POLYGON_API_KEY") != key:
        print("FAIL: build_scan_process_env")
        return 1
    _ok, msg = validate_polygon_api_key()
    if "חסר מפתח" in msg:
        print(f"FAIL: validate without arg: {msg}")
        return 1
    settings = load_settings()
    if settings.provider == "polygon" and not settings.get_polygon_key():
        print("FAIL: load_settings missing polygon key")
        return 1
    _ok2, msg2 = validate_polygon_api_key(settings.get_polygon_key())
    if "חסר מפתח" in msg2:
        print(f"FAIL: validate with settings key: {msg2}")
        return 1
    print("POLYGON_KEY_PATH OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
