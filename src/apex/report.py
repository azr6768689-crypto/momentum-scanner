"""CSV report export for Apex scanner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.apex.models import APEX_COLUMNS, ApexScanResult


def results_to_dataframe(results: list[ApexScanResult]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for rank, r in enumerate(results, start=1):
        row = r.to_row(rank)
        if isinstance(row.get("chart_json"), list):
            row["chart_json"] = json.dumps(row["chart_json"], ensure_ascii=False)
        rows.append(row)
    return pd.DataFrame(rows, columns=APEX_COLUMNS)


def write_apex_report(results: list[ApexScanResult], path: Path | str) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    df = results_to_dataframe(results)
    df.to_csv(out, index=False, encoding="utf-8")
    return out
