"""Compare today's report with the previous official report (same profile)."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from src.report_paths import OFFICIAL_REPORT_SUFFIXES, is_official_report_csv


def report_date_and_suffix(path: Path) -> tuple[str, str]:
    name = path.name
    m = re.match(r"(\d{4}-\d{2}-\d{2})_(.+)_report\.csv$", name)
    if m:
        return m.group(1), m.group(2)
    m2 = re.match(r"(\d{4}-\d{2}-\d{2})_report\.csv$", name)
    if m2:
        return m2.group(1), "legacy"
    return "", ""


def find_previous_report_path(current: Path, reports_dir: Path) -> Path | None:
    """Latest official report with same suffix and an earlier date."""
    cur_date, suffix = report_date_and_suffix(current)
    if not cur_date:
        return None
    candidates: list[tuple[str, Path]] = []
    if not reports_dir.exists():
        return None
    for path in reports_dir.glob("*_report.csv"):
        if not is_official_report_csv(path):
            continue
        date_part, file_suffix = report_date_and_suffix(path)
        if date_part >= cur_date:
            continue
        if suffix == "legacy" and file_suffix == "legacy":
            candidates.append((date_part, path))
        elif suffix in OFFICIAL_REPORT_SUFFIXES and file_suffix == suffix:
            candidates.append((date_part, path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def attach_rank_delta(
    df: pd.DataFrame,
    current_report: Path,
    *,
    load_report_fn,
) -> tuple[pd.DataFrame, str]:
    """
    Add columns: דירוג אתמול, שינוי דירוג, שינוי דירוג מספר.
    Positive שינוי דירוג מספר = improved rank vs yesterday.
    """
    out = df.copy()
    out["דירוג אתמול"] = ""
    out["שינוי דירוג"] = "—"
    out["שינוי דירוג מספר"] = 0

    if out.empty or "סימבול" not in out.columns or "דירוג" not in out.columns:
        return out, ""

    prev_path = find_previous_report_path(current_report, current_report.parent)
    if prev_path is None:
        return out, ""

    prev_date, _ = report_date_and_suffix(prev_path)
    prev_stat = prev_path.stat()
    prev_df = load_report_fn(str(prev_path), prev_stat.st_size, prev_stat.st_mtime_ns)
    if prev_df.empty or "דירוג" not in prev_df.columns:
        return out, prev_date

    prev_ranks: dict[str, int] = {}
    for sym, rank in zip(prev_df["סימבול"], prev_df["דירוג"]):
        if pd.isna(rank):
            continue
        try:
            prev_ranks[str(sym).upper().strip()] = int(rank)
        except (TypeError, ValueError):
            continue

    yest_list: list[str] = []
    delta_list: list[str] = []
    num_list: list[int] = []

    for _, row in out.iterrows():
        sym = str(row["סימבול"]).upper().strip()
        try:
            today_rank = int(row["דירוג"])
        except (TypeError, ValueError):
            today_rank = 9999

        if sym not in prev_ranks:
            yest_list.append("")
            delta_list.append("חדש")
            num_list.append(40)
            continue

        y_rank = prev_ranks[sym]
        yest_list.append(str(y_rank))
        diff = y_rank - today_rank
        if diff > 0:
            delta_list.append(f"↑{diff}")
            num_list.append(diff)
        elif diff < 0:
            delta_list.append(f"↓{abs(diff)}")
            num_list.append(diff)
        else:
            delta_list.append("=")
            num_list.append(0)

    out["דירוג אתמול"] = yest_list
    out["שינוי דירוג"] = delta_list
    out["שינוי דירוג מספר"] = num_list
    return out, prev_date
