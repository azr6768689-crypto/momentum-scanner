"""Pre-built scan filters — Trade Ideas-style strategies on daily Apex report."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd


@dataclass(frozen=True)
class ScanPreset:
    id: str
    name_he: str
    description_he: str
    filter_fn: Callable[[pd.DataFrame], pd.Series]


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    if name not in df.columns:
        return pd.Series(False, index=df.index)
    return df[name]


def list_presets() -> list[ScanPreset]:
    return [
        ScanPreset(
            id="ti_breakout",
            name_he="פריצה + ווליום (TI)",
            description_he="Apex≥75, RS≥70, RVOL≥1.5, דפוס Breakout/52W/Squeeze",
            filter_fn=lambda df: (
                (pd.to_numeric(_col(df, "Apex Score"), errors="coerce") >= 75)
                & (pd.to_numeric(_col(df, "RS Rating"), errors="coerce") >= 70)
                & (pd.to_numeric(_col(df, "RVOL"), errors="coerce") >= 1.5)
                & _col(df, "דפוס").astype(str).str.contains("Breakout|52W|Squeeze", case=False, na=False)
            ),
        ),
        ScanPreset(
            id="ti_momentum",
            name_he="מומנטום מוביל",
            description_he="Apex≥80, RS≥80, מגמה A או B",
            filter_fn=lambda df: (
                (pd.to_numeric(_col(df, "Apex Score"), errors="coerce") >= 80)
                & (pd.to_numeric(_col(df, "RS Rating"), errors="coerce") >= 80)
                & (
                    _col(df, "מגמה").astype(str).str.startswith("A", na=False)
                    | _col(df, "מגמה").astype(str).str.startswith("B", na=False)
                )
            ),
        ),
        ScanPreset(
            id="ti_pullback",
            name_he="פולבק במגמה",
            description_he="דפוס Pullback/Flag, Apex≥65, מעל MA50",
            filter_fn=lambda df: (
                (pd.to_numeric(_col(df, "Apex Score"), errors="coerce") >= 65)
                & _col(df, "דפוס").astype(str).str.contains("Pullback|Flag", case=False, na=False)
            ),
        ),
        ScanPreset(
            id="ti_gap_rvol",
            name_he="תנועה חזקה היום",
            description_he="שינוי יום ≥3%, RVOL≥2",
            filter_fn=lambda df: (
                (pd.to_numeric(_col(df, "שינוי %"), errors="coerce") >= 3)
                & (pd.to_numeric(_col(df, "RVOL"), errors="coerce") >= 2)
            ),
        ),
    ]


def run_preset_on_report(df: pd.DataFrame, preset_id: str) -> pd.DataFrame:
    for p in list_presets():
        if p.id == preset_id:
            mask = p.filter_fn(df)
            return df[mask].copy()
    raise ValueError(f"Unknown preset {preset_id}")
