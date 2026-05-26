"""Data models for Apex scanner results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MarketContext:
    regime: str
    score: int
    spy_trend: str
    qqq_trend: str
    long_bias: str
    note: str


@dataclass
class ApexScanResult:
    ticker: str
    sector: str
    data_source: str

    apex_score: int
    rs_rating: int
    trend_grade: str
    setup_type: str
    institutional_grade: str
    timing_score: int
    volume_score: int
    risk_reward: float

    last_close: float
    pct_change_1d: float
    rvol: float
    dist_52w_high_pct: float
    rs_vs_spy_20d: float
    rs_vs_qqq_20d: float

    market_regime: str
    market_score: int

    sma20: float
    sma50: float
    sma200: float | None
    atr14: float
    rsi14: float
    adx14: float

    entry: float
    stop: float
    target_1: float
    target_2: float
    trigger: str

    summary: str
    flags: list[str] = field(default_factory=list)
    chart_ohlcv: list[dict[str, Any]] = field(default_factory=list)

    def to_row(self, rank: int) -> dict[str, Any]:
        return {
            "דירוג": rank,
            "סימבול": self.ticker,
            "סקטור": self.sector,
            "Apex Score": self.apex_score,
            "RS Rating": self.rs_rating,
            "מגמה": self.trend_grade,
            "דפוס": self.setup_type,
            "רמת מוסדי": self.institutional_grade,
            "תזמון": self.timing_score,
            "ווליום": self.volume_score,
            "R:R": round(self.risk_reward, 2),
            "מחיר": round(self.last_close, 2),
            "שינוי %": round(self.pct_change_1d, 2),
            "RVOL": round(self.rvol, 2),
            "מרחק 52w %": round(self.dist_52w_high_pct, 2),
            "RS vs SPY %": round(self.rs_vs_spy_20d, 2),
            "RS vs QQQ %": round(self.rs_vs_qqq_20d, 2),
            "מצב שוק": self.market_regime,
            "ציון שוק": self.market_score,
            "טריגר": self.trigger,
            "כניסה": round(self.entry, 2),
            "סטופ": round(self.stop, 2),
            "יעד 1": round(self.target_1, 2),
            "יעד 2": round(self.target_2, 2),
            "SMA20": round(self.sma20, 2),
            "SMA50": round(self.sma50, 2),
            "SMA200": "" if self.sma200 is None else round(self.sma200, 2),
            "ATR14": round(self.atr14, 2),
            "RSI": round(self.rsi14, 1),
            "ADX": round(self.adx14, 1),
            "סיכום": self.summary,
            "דגלים": " | ".join(self.flags),
            "מקור נתונים": self.data_source,
            "chart_json": self.chart_ohlcv,
        }


APEX_COLUMNS = [
    "דירוג",
    "סימבול",
    "סקטור",
    "Apex Score",
    "RS Rating",
    "מגמה",
    "דפוס",
    "רמת מוסדי",
    "תזמון",
    "ווליום",
    "R:R",
    "מחיר",
    "שינוי %",
    "RVOL",
    "מרחק 52w %",
    "RS vs SPY %",
    "RS vs QQQ %",
    "מצב שוק",
    "ציון שוק",
    "טריגר",
    "כניסה",
    "סטופ",
    "יעד 1",
    "יעד 2",
    "SMA20",
    "SMA50",
    "SMA200",
    "ATR14",
    "RSI",
    "ADX",
    "סיכום",
    "דגלים",
    "מקור נתונים",
    "chart_json",
]
