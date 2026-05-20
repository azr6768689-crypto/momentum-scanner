#!/usr/bin/env python3
"""Remove non-official test/bench report CSVs from data/reports/."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.report_paths import is_official_report_csv

REPORTS_DIR = ROOT / "data" / "reports"


def main() -> int:
    if not REPORTS_DIR.exists():
        print("No reports directory.")
        return 0
    removed = []
    kept = []
    for path in sorted(REPORTS_DIR.glob("*_report.csv")):
        if is_official_report_csv(path):
            kept.append(path.name)
        else:
            path.unlink()
            removed.append(path.name)
    print(f"Kept {len(kept)} official report(s).")
    for name in kept:
        print(f"  ✓ {name}")
    if removed:
        print(f"Removed {len(removed)} legacy/test file(s):")
        for name in removed:
            print(f"  ✗ {name}")
    else:
        print("Nothing to remove.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
