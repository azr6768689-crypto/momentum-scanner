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
    env = build_scan_subprocess_env({})
    if "SCAN_PROGRESS_PATH" not in env:
        print("FAIL: missing SCAN_PROGRESS_PATH")
        return 1
    if env.get("DATA_PROVIDER") != "demo":
        print("FAIL: DATA_PROVIDER not preserved")
        return 1
    print("SCAN_RUNTIME OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
