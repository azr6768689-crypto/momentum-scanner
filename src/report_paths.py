"""Report file naming helpers (shared by dashboard and maintenance scripts)."""
from __future__ import annotations

import re
from pathlib import Path

OFFICIAL_REPORT_SUFFIXES = frozenset({"us_simple", "us_medium", "us_full", "apex"})


def is_official_report_csv(path: Path) -> bool:
    name = path.name
    if re.match(r"\d{4}-\d{2}-\d{2}_report\.csv$", name):
        return True
    m = re.match(r"\d{4}-\d{2}-\d{2}_(.+)_report\.csv$", name)
    return bool(m and m.group(1) in OFFICIAL_REPORT_SUFFIXES)
