#!/usr/bin/env python3
"""Regression: scan subprocess env is provider-agnostic."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.scan_runtime import build_scan_subprocess_env


def main() -> int:
    os.environ["DATA_PROVIDER"] = "demo"
    os.environ["SCAN_ALLOW_DEMO"] = "1"
    env = build_scan_subprocess_env({})
    if "SCAN_PROGRESS_PATH" not in env:
        print("FAIL: missing SCAN_PROGRESS_PATH")
        return 1
    # With a Polygon key on disk, subprocess env correctly upgrades to polygon.
    if env.get("DATA_PROVIDER") not in {"demo", "polygon"}:
        print(f"FAIL: unexpected DATA_PROVIDER={env.get('DATA_PROVIDER')}")
        return 1
    print("SCAN_RUNTIME OK")
    print(f"DATA_PROVIDER={env.get('DATA_PROVIDER')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
