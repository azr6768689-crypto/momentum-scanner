"""
Professional long-only momentum setup detector.

This module builds a practical Hebrew report for swing-trading candidates.
It does not produce buy/sell recommendations. It ranks long-only setups by
trend, breakout proximity, volume behavior, volatility compression, and risk.
"""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)

import pandas as pd

from src.analytics.indicators import IndicatorSnapshot


HEBREW_COLUMNS = [
    "דירוג",
    "מקור נתונים",
    "סימבול",
    "סקטור",
    "חוזק סקטור 20 יום %",
    "ציון סקטור",
    "דירוג סקטור",
    "הערת סקטור",
    "גרף קטן",
    "גרף יומי",
    "גרף שבועי",
    "גרף שעתי",
    "מחיר אחרון",
    "שינוי %",
    "ווליום יחסי",
    "ציון מוסדי",
    "תג מוסדי",
    "חוזק יחסי SPY 20 יום %",
    "חוזק יחסי QQQ 20 יום %",
    "איכות נר",
    "אישור ווליום",
    "הערת מוסדיים",
    "מצב שוק",
    "ציון שוק",
    "אישור שוק ללונג",
    "הערת שוק",
    "מגמה",
    "דפוס",
    "הצלחה היסטורית %",
    "דגימות היסטוריות",
    "תשואה היסטורית ממוצעת %",
    "הערת Backtest",
    "חדשות אחרונות",
    "ציון חדשות",
    "קטליסט",
    "תאריך חדשות",
    "מצב פריצה",
    "הסתברות %",
    "סיכוי למהלך %",
    "רמה",
    "RSI",
    "MACD",
    "ADX",
    "CCI",
    "SMA20",
    "SMA50",
    "SMA200",
    "ATR14",
    "מרחק מ-SMA20 %",
    "מרחק מ-SMA50 %",
    "מרחק מפריצת 20 יום %",
    "מרחק מפריצת 50 יום %",
    "דולר ווליום 20 יום",
    "שורט אינטרסט",
    "שורט פלואט %",
    "שורט חריג",
    "הסבר",
    "נקודת כניסה",
    "סטופ / ביטול",
    "יעד ראשון",
    "יעד שני",
    "התנגדות קרובה",
    "מימוש רווח",
    "הסתברות יעד ראשון %",
    "הסתברות יעד שני %",
    "זמן משוער ליעדים",
    "הערת סיכון",
    "מה לחכות",
]


@dataclass(frozen=True)
class LongSetup:
    ticker: str
    sector: str
    sector_strength_20d: float | None
    sector_score: int
    sector_rank: str
    sector_note: str
    last_close: float | None
    pct_change: float | None
    rvol: float | None
    institutional_score: int
    institutional_tag: str
    rs_spy_20: float | None
    rs_qqq_20: float | None
    candle_quality: str
    volume_confirmation: str
    institutional_note: str
    market_regime: str
    market_score: int
    market_long_support: str
    market_note: str
    trend: str
    pattern: str
    historical_success_rate: float | None
    historical_sample_size: int
    historical_avg_forward_return: float | None
    backtest_note: str
    breakout_status: str
    probability: int
    level: str
    rsi: float | None
    macd: str
    adx: float | None
    cci: float | None
    sma20: float | None
    sma50: float | None
    sma200: float | None
    atr14: float | None
    dist_sma20: float | None
    dist_sma50: float | None
    breakout_20: float | None
    breakout_50: float | None
    dollar_volume_20: float | None
    short_interest: str
    short_float_pct: str
    short_unusual: str
    explanation: str
    entry: float | None
    stop: str
    target_1: float | None
    target_2: float | None
    resistance_zone: str
    profit_take_plan: str
    target_1_probability: int
    target_2_probability: int
    time_to_targets: str
    risk_note: str
    wait_for: str
    sparkline: str
    daily_sparkline: str
    weekly_sparkline: str
    hourly_sparkline: str


def _data_source_label() -> str:
    provider = os.getenv("DATA_PROVIDER", "demo").strip().lower() or "demo"
    labels = {
        "demo": "דמו (סינתטי — לא מחירי שוק)",
        "polygon": "Polygon (מחירים מותאמים)",
        "tiingo": "Tiingo",
    }
    return labels.get(provider, provider)


def build_professional_long_rows(
    tickers: list[str],
    universe: dict[str, pd.DataFrame],
    snapshots: dict[str, IndicatorSnapshot],
    sector_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Return ranked Hebrew rows for the fixed long-only universe."""
    sector_map = sector_map or {}
    data_source = _data_source_label()
    spy_df = universe.get("SPY")
    qqq_df = universe.get("QQQ")
    market = _market_regime(snapshots.get("SPY"), snapshots.get("QQQ"), snapshots.get("IWM"))
    sector_stats = _sector_strength(sector_map, universe, snapshots)

    def _analyze_one(ticker: str):
        sector = sector_map.get(ticker, "לא זמין")
        return _analyze_ticker(
            ticker,
            universe.get(ticker),
            snapshots.get(ticker),
            spy_df,
            qqq_df,
            market,
            sector,
            sector_stats.get(sector, _neutral_sector("לא זמין")),
        )

    from src.scan_progress import write_progress
    from src.scan_runtime import cap_scan_workers

    workers_raw = os.getenv("SCAN_ANALYZE_WORKERS", "").strip()
    if workers_raw.isdigit() and int(workers_raw) > 0:
        workers = cap_scan_workers(int(workers_raw))
    else:
        workers = cap_scan_workers(min(8, os.cpu_count() or 4))
    profile_id = os.getenv("SCAN_PROFILE", "").strip()
    profile_label = os.getenv("SCAN_PROFILE_LABEL", "").strip() or "סריקה"
    total = len(tickers)
    setups: list[LongSetup] = []
    analyze_timeout = int(os.getenv("SCAN_ANALYZE_TIMEOUT", "60"))
    if len(tickers) >= 80 and workers > 1:
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_analyze_one, t): t for t in tickers}
            for future in as_completed(futures):
                ticker_key = futures[future]
                try:
                    setups.append(future.result(timeout=analyze_timeout))
                except FuturesTimeoutError:
                    _log.warning("Analyze timeout for %s after %ds", ticker_key, analyze_timeout)
                    setups.append(_analyze_one(ticker_key) if False else _empty_setup(ticker_key, sector_map.get(ticker_key, "לא זמין"), market, sector_stats))
                except Exception as exc:
                    _log.warning("Analyze error for %s: %s", ticker_key, exc)
                    setups.append(_empty_setup(ticker_key, sector_map.get(ticker_key, "לא זמין"), market, sector_stats))
                done += 1
                if done == 1 or done % 40 == 0 or done == total:
                    pct = 78 + int(10 * done / max(total, 1))
                    write_progress(
                        pct,
                        "דירוג",
                        done=done,
                        total=total,
                        message=f"{profile_label}: מדרג {done:,}/{total:,}",
                        profile_id=profile_id,
                        profile_label=profile_label,
                    )
    else:
        for idx, t in enumerate(tickers, start=1):
            setups.append(_analyze_one(t))
            if idx == 1 or idx % 40 == 0 or idx == total:
                pct = 78 + int(10 * idx / max(total, 1))
                write_progress(
                    pct,
                    "דירוג",
                    done=idx,
                    total=total,
                    message=f"{profile_label}: מדרג {idx:,}/{total:,}",
                    profile_id=profile_id,
                    profile_label=profile_label,
                )
    setups.sort(key=lambda setup: (setup.probability, setup.institutional_score, setup.ticker), reverse=True)

    rows: list[dict[str, Any]] = []
    for rank, setup in enumerate(setups, start=1):
        rows.append({
            "דירוג": rank,
            "מקור נתונים": data_source,
            "סימבול": setup.ticker,
            "סקטור": setup.sector,
            "חוזק סקטור 20 יום %": _round_or_blank(setup.sector_strength_20d),
            "ציון סקטור": setup.sector_score,
            "דירוג סקטור": setup.sector_rank,
            "הערת סקטור": setup.sector_note,
            "גרף קטן": setup.sparkline,
            "גרף יומי": setup.daily_sparkline,
            "גרף שבועי": setup.weekly_sparkline,
            "גרף שעתי": setup.hourly_sparkline,
            "מחיר אחרון": _round_or_blank(setup.last_close),
            "שינוי %": _round_or_blank(setup.pct_change),
            "ווליום יחסי": _round_or_blank(setup.rvol),
            "ציון מוסדי": setup.institutional_score,
            "תג מוסדי": setup.institutional_tag,
            "חוזק יחסי SPY 20 יום %": _round_or_blank(setup.rs_spy_20),
            "חוזק יחסי QQQ 20 יום %": _round_or_blank(setup.rs_qqq_20),
            "איכות נר": setup.candle_quality,
            "אישור ווליום": setup.volume_confirmation,
            "הערת מוסדיים": setup.institutional_note,
            "מצב שוק": setup.market_regime,
            "ציון שוק": setup.market_score,
            "אישור שוק ללונג": setup.market_long_support,
            "הערת שוק": setup.market_note,
            "מגמה": setup.trend,
            "דפוס": setup.pattern,
            "הצלחה היסטורית %": _round_or_blank(setup.historical_success_rate),
            "דגימות היסטוריות": setup.historical_sample_size,
            "תשואה היסטורית ממוצעת %": _round_or_blank(setup.historical_avg_forward_return),
            "הערת Backtest": setup.backtest_note,
            "חדשות אחרונות": "",
            "ציון חדשות": "",
            "קטליסט": "",
            "תאריך חדשות": "",
            "מצב פריצה": setup.breakout_status,
            "הסתברות %": setup.probability,
            "סיכוי למהלך %": setup.probability,
            "רמה": setup.level,
            "RSI": _round_or_blank(setup.rsi),
            "MACD": setup.macd,
            "ADX": _round_or_blank(setup.adx),
            "CCI": _round_or_blank(setup.cci),
            "SMA20": _round_or_blank(setup.sma20),
            "SMA50": _round_or_blank(setup.sma50),
            "SMA200": _round_or_blank(setup.sma200),
            "ATR14": _round_or_blank(setup.atr14),
            "מרחק מ-SMA20 %": _round_or_blank(setup.dist_sma20),
            "מרחק מ-SMA50 %": _round_or_blank(setup.dist_sma50),
            "מרחק מפריצת 20 יום %": _round_or_blank(setup.breakout_20),
            "מרחק מפריצת 50 יום %": _round_or_blank(setup.breakout_50),
            "דולר ווליום 20 יום": _round_or_blank(setup.dollar_volume_20),
            "שורט אינטרסט": setup.short_interest,
            "שורט פלואט %": setup.short_float_pct,
            "שורט חריג": setup.short_unusual,
            "הסבר": setup.explanation,
            "נקודת כניסה": _round_or_blank(setup.entry),
            "סטופ / ביטול": setup.stop,
            "יעד ראשון": _round_or_blank(setup.target_1),
            "יעד שני": _round_or_blank(setup.target_2),
            "התנגדות קרובה": setup.resistance_zone,
            "מימוש רווח": setup.profit_take_plan,
            "הסתברות יעד ראשון %": setup.target_1_probability,
            "הסתברות יעד שני %": setup.target_2_probability,
            "זמן משוער ליעדים": setup.time_to_targets,
            "הערת סיכון": setup.risk_note,
            "מה לחכות": setup.wait_for,
        })
    if os.getenv("SCAN_SKIP_BACKTEST", "").strip().lower() not in {"1", "true", "yes", "on"}:
        _apply_strategy_backtest_aggregates(rows)
    return rows


def write_professional_long_report(
    tickers: list[str],
    universe: dict[str, pd.DataFrame],
    snapshots: dict[str, IndicatorSnapshot],
    output_path: str | Any,
    sector_map: dict[str, str] | None = None,
) -> None:
    rows = build_professional_long_rows(tickers, universe, snapshots, sector_map=sector_map)
    pd.DataFrame(rows, columns=HEBREW_COLUMNS).to_csv(output_path, index=False, encoding="utf-8")


def _apply_strategy_backtest_aggregates(rows: list[dict[str, Any]]) -> None:
    by_pattern: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        pattern = str(row.get("דפוס") or "")
        samples = int(row.get("דגימות היסטוריות") or 0)
        success = row.get("הצלחה היסטורית %")
        avg_return = row.get("תשואה היסטורית ממוצעת %")
        if pattern in {"", "לא נבדק", "אין דפוס פריצה איכותי כרגע"} or samples < 3:
            continue
        if success == "" or avg_return == "":
            continue
        by_pattern.setdefault(pattern, []).append({
            "samples": samples,
            "success": float(success),
            "avg_return": float(avg_return),
        })

    aggregates: dict[str, dict[str, float | int]] = {}
    for pattern, items in by_pattern.items():
        total_samples = sum(int(item["samples"]) for item in items)
        if total_samples < 8:
            continue
        aggregates[pattern] = {
            "samples": total_samples,
            "success": sum(float(item["success"]) * int(item["samples"]) for item in items) / total_samples,
            "avg_return": sum(float(item["avg_return"]) * int(item["samples"]) for item in items) / total_samples,
        }

    for row in rows:
        pattern = str(row.get("דפוס") or "")
        if pattern not in aggregates:
            continue
        if int(row.get("דגימות היסטוריות") or 0) >= 3:
            row["הערת Backtest"] = "Backtest מקומי למניה: " + str(row.get("הערת Backtest", ""))
            continue
        aggregate = aggregates[pattern]
        row["הצלחה היסטורית %"] = round(float(aggregate["success"]), 2)
        row["דגימות היסטוריות"] = int(aggregate["samples"])
        row["תשואה היסטורית ממוצעת %"] = round(float(aggregate["avg_return"]), 2)
        row["הערת Backtest"] = (
            f"Backtest אגרגטיבי לפי אסטרטגיה: {float(aggregate['success']):.0f}% הצלחה "
            f"מתוך {int(aggregate['samples'])} מופעים דומים בכל המניות בדפוס {pattern}."
        )


def _empty_setup(
    ticker: str,
    sector: str = "לא זמין",
    market: dict[str, Any] | None = None,
    sector_stats: dict[str, dict[str, Any]] | None = None,
) -> LongSetup:
    """Return a minimal no-data setup for tickers that timed out or errored."""
    market = market or _market_regime(None, None, None)
    si = (sector_stats or {}).get(sector) or _neutral_sector(sector)
    return _analyze_ticker(ticker, None, None, market=market, sector=sector, sector_info=si)


def _analyze_ticker(
    ticker: str,
    df: pd.DataFrame | None,
    snap: IndicatorSnapshot | None,
    spy_df: pd.DataFrame | None = None,
    qqq_df: pd.DataFrame | None = None,
    market: dict[str, Any] | None = None,
    sector: str = "לא זמין",
    sector_info: dict[str, Any] | None = None,
) -> LongSetup:
    market = market or _market_regime(None, None, None)
    sector_info = sector_info or _neutral_sector(sector)
    if df is None or df.empty or snap is None:
        return LongSetup(
            ticker=ticker,
            sector=sector,
            sector_strength_20d=sector_info["avg_return_20d"],
            sector_score=sector_info["score"],
            sector_rank=sector_info["rank"],
            sector_note=sector_info["note"],
            last_close=None,
            pct_change=None,
            rvol=None,
            institutional_score=0,
            institutional_tag="אין דאטה",
            rs_spy_20=None,
            rs_qqq_20=None,
            candle_quality="אין דאטה",
            volume_confirmation="אין דאטה",
            institutional_note="אין מספיק דאטה לשכבת אישור מוסדי.",
            market_regime=market["regime"],
            market_score=market["score"],
            market_long_support=market["long_support"],
            market_note=market["note"],
            trend="אין דאטה",
            pattern="לא נבדק",
            historical_success_rate=None,
            historical_sample_size=0,
            historical_avg_forward_return=None,
            backtest_note="אין מספיק דאטה לבדיקת מופעים היסטוריים.",
            breakout_status="אין מספיק דאטה עדכני",
            probability=0,
            level="אין דירוג",
            rsi=None,
            macd="אין דאטה",
            adx=None,
            cci=None,
            sma20=None,
            sma50=None,
            sma200=None,
            atr14=None,
            dist_sma20=None,
            dist_sma50=None,
            breakout_20=None,
            breakout_50=None,
            dollar_volume_20=None,
            short_interest="לא זמין",
            short_float_pct="לא זמין",
            short_unusual="לא נבדק",
            explanation="לא התקבל דאטה שימושי למניה הזו כרגע, לכן אי אפשר לאשר פריצה או דפוס איכותי.",
            entry=None,
            stop="אין סטופ תקף בלי דאטה",
            target_1=None,
            target_2=None,
            resistance_zone="אין דאטה",
            profit_take_plan="אין תוכנית מימוש בלי דאטה עדכני.",
            target_1_probability=0,
            target_2_probability=0,
            time_to_targets="אין הערכת זמן בלי דאטה",
            risk_note="לא לפעול בלי דאטה עדכני.",
            wait_for="להמתין לרענון דאטה.",
            sparkline="[]",
            daily_sparkline="[]",
            weekly_sparkline="[]",
            hourly_sparkline="[]",
        )

    close = snap.close
    near_20 = -2.0 <= snap.breakout_dist_20d_pct < 0
    broke_20 = snap.breakout_dist_20d_pct >= 0
    near_50 = -3.0 <= snap.breakout_dist_50d_pct < 0
    broke_50 = snap.breakout_dist_50d_pct >= 0
    strong_trend = snap.trend == "uptrend_strong"
    weak_trend = snap.trend == "uptrend_weak"
    active_volume = snap.rvol_20 >= 1.3
    high_volume = snap.rvol_20 >= 1.8
    extended = snap.atr_ext_above_sma20 > 3.0
    compression = _has_compression(df)
    cup_handle = _cup_handle_candidate(df, snap)
    bull_flag = _bull_flag_candidate(df, snap)
    trend_reversal = _trend_reversal_candidate(df, snap)
    pullback_20 = _pullback_to_sma20_candidate(df, snap)
    reclaim_50 = _reclaim_sma50_candidate(df, snap)
    breakout_52w = _fifty_two_week_breakout_candidate(snap)
    volume_dry_up = _volume_dry_up_candidate(df, snap)
    def _env_on(name: str) -> bool:
        return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}

    skip_all_sparklines = _env_on("SCAN_SKIP_SPARKLINES")
    compact_charts = _env_on("SCAN_FAST_CHARTS") or _env_on("SCAN_FAST")
    skip_weekly = _env_on("SCAN_SKIP_WEEKLY_SPARKLINES") or skip_all_sparklines
    technicals = _technical_state(df.tail(min(len(df), 120)))

    score = 0
    reasons: list[str] = []

    if strong_trend:
        score += 24
        reasons.append("המניה במגמה עולה חזקה")
    elif weak_trend:
        score += 14
        reasons.append("המניה מעל אזור מגמה מרכזי אבל לא במבנה מושלם")
    else:
        reasons.append("המגמה עדיין לא מספיק חזקה ללונג איכותי")

    if broke_20:
        score += 18
        reasons.append("המחיר כבר מעל שיא 20 ימים")
    elif near_20:
        score += 15
        reasons.append("המחיר קרוב מאוד לרמת פריצה של 20 ימים")
    elif near_50 or broke_50:
        score += 10
        reasons.append("המחיר קרוב לאזור פריצה רחב יותר")

    if high_volume:
        score += 18
        reasons.append("הווליום היחסי חזק ומאשר עניין")
    elif active_volume:
        score += 10
        reasons.append("יש התעוררות בווליום")
    else:
        reasons.append("חסר אישור ווליום חזק")

    if strong_trend and near_20:
        score += 8
        reasons.append("המחיר יושב ממש מתחת לרמת פריצה ולכן שווה מעקב קרוב")

    if compression:
        score += 14
        reasons.append("יש התכווצות תנודתיות לפני אפשרות פריצה")
    if bull_flag:
        score += 12
        reasons.append("המבנה דומה לדגל שורי / המשך מומנטום")
    if cup_handle:
        score += 16
        reasons.append("המבנה דומה ל־Cup & Handle ראשוני")
    if breakout_52w:
        score += 18
        reasons.append("המחיר קרוב או פורץ שיא 52 שבועות, מצב מוסדי קלאסי של חוזק")
    if trend_reversal:
        score += 14
        reasons.append("יש סימני היפוך מגמה חיובי אחרי חולשה קודמת")
    if pullback_20:
        score += 12
        reasons.append("פולבק מסודר לממוצע 20 בתוך מגמה עולה")
    if reclaim_50:
        score += 10
        reasons.append("המחיר החזיר שליטה מעל ממוצע 50")
    if volume_dry_up:
        score += 8
        reasons.append("יש ירידת ווליום בהתכנסות, מצב שמרמז על היעדר מוכרים לפני פריצה")

    if snap.pct_change_1d > 0:
        score += min(8, int(round(snap.pct_change_1d * 2)))
    if close > snap.sma20:
        score += 5
    if close > snap.sma50:
        score += 5
    if extended:
        score -= 12
        reasons.append("אבל המחיר מתוח מדי מעל ממוצע 20 ולכן כניסה מיידית מסוכנת")

    score += technicals["score_bonus"]
    reasons.extend(technicals["reasons"])
    score += int(market["score_adjust"])
    reasons.append(str(market["note"]))
    score += int(sector_info["score_adjust"])
    reasons.append(str(sector_info["note"]))

    pattern = _pattern_name(
        cup_handle,
        bull_flag,
        compression,
        broke_20,
        near_20,
        near_50,
        trend_reversal,
        pullback_20,
        reclaim_50,
        breakout_52w,
        volume_dry_up,
    )
    breakout_status = _breakout_status(snap)
    if os.getenv("SCAN_SKIP_BACKTEST", "").strip().lower() in {"1", "true", "yes", "on"}:
        backtest = {
            "success_rate": None,
            "sample_size": 0,
            "avg_forward_return": None,
            "score_adjust": 0,
            "note": "Backtest מקומי דולג במצב סריקה מהירה.",
        }
    else:
        backtest = _strategy_backtest(df, pattern)
    if backtest["score_adjust"]:
        score += int(backtest["score_adjust"])
        reasons.append(str(backtest["note"]))
    score = max(0, min(100, score))
    actionable_breakout = broke_20 or snap.breakout_dist_20d_pct >= -1.5 or breakout_52w or reclaim_50
    has_quality_pattern = pattern != "אין דפוס פריצה איכותי כרגע"
    has_volume_context = snap.rvol_20 >= 0.8 or high_volume or active_volume
    level = _level(score, actionable_breakout, has_quality_pattern, has_volume_context, extended)
    entry = max(close * 1.005, snap.prior_high_20d * 1.001)
    numeric_stop = min(snap.sma20, close - 1.5 * snap.atr14)
    target_1 = entry + 2.0 * (entry - numeric_stop)
    trade_plan = _target_plan(score, entry, numeric_stop, target_1, snap)
    institutional = _institutional_layer(df, snap, score, level, pattern, spy_df, qqq_df)

    return LongSetup(
        ticker=ticker,
        sector=sector,
        sector_strength_20d=sector_info["avg_return_20d"],
        sector_score=sector_info["score"],
        sector_rank=sector_info["rank"],
        sector_note=sector_info["note"],
        last_close=close,
        pct_change=snap.pct_change_1d,
        rvol=snap.rvol_20,
        institutional_score=institutional["score"],
        institutional_tag=institutional["tag"],
        rs_spy_20=institutional["rs_spy_20"],
        rs_qqq_20=institutional["rs_qqq_20"],
        candle_quality=institutional["candle_quality"],
        volume_confirmation=institutional["volume_confirmation"],
        institutional_note=institutional["note"],
        market_regime=market["regime"],
        market_score=market["score"],
        market_long_support=market["long_support"],
        market_note=market["note"],
        trend=_trend_hebrew(snap.trend),
        pattern=pattern,
        historical_success_rate=backtest["success_rate"],
        historical_sample_size=backtest["sample_size"],
        historical_avg_forward_return=backtest["avg_forward_return"],
        backtest_note=backtest["note"],
        breakout_status=breakout_status,
        probability=score,
        level=level,
        rsi=technicals["rsi"],
        macd=technicals["macd_label"],
        adx=technicals["adx"],
        cci=technicals["cci"],
        sma20=snap.sma20,
        sma50=snap.sma50,
        sma200=snap.sma200,
        atr14=snap.atr14,
        dist_sma20=snap.dist_from_sma20_pct,
        dist_sma50=snap.dist_from_sma50_pct,
        breakout_20=snap.breakout_dist_20d_pct,
        breakout_50=snap.breakout_dist_50d_pct,
        dollar_volume_20=snap.dollar_volume_20,
        short_interest="לא זמין",
        short_float_pct="לא זמין",
        short_unusual="דורש מקור short interest נוסף",
        explanation="; ".join(reasons) + ".",
        entry=entry,
        stop=f"מתחת ${numeric_stop:.2f} או סגירה מתחת ממוצע 20",
        target_1=target_1,
        target_2=trade_plan["target_2"],
        resistance_zone=trade_plan["resistance_zone"],
        profit_take_plan=trade_plan["profit_take_plan"],
        target_1_probability=trade_plan["target_1_probability"],
        target_2_probability=trade_plan["target_2_probability"],
        time_to_targets=trade_plan["time_to_targets"],
        risk_note=_risk_note(score, extended, snap.rvol_20),
        wait_for=f"לחכות לפריצה מעל ${entry:.2f} עם ווליום יחסי מעל 1.5x ונר שסוגר חזק.",
        sparkline="[]" if skip_all_sparklines else _daily_sparkline(df, bars=40 if compact_charts else 80),
        daily_sparkline="[]" if skip_all_sparklines else _daily_sparkline(df, bars=40 if compact_charts else 80),
        weekly_sparkline="[]" if skip_weekly else _weekly_sparkline(df),
        hourly_sparkline="[]",
    )


def _has_compression(df: pd.DataFrame) -> bool:
    if len(df) < 30:
        return False
    recent_range = (df["high"].tail(10).max() - df["low"].tail(10).min()) / df["close"].iloc[-1]
    prior_range = (df["high"].tail(30).head(20).max() - df["low"].tail(30).head(20).min()) / df["close"].iloc[-1]
    return recent_range < prior_range * 0.7


def _strategy_backtest(df: pd.DataFrame, pattern: str) -> dict[str, Any]:
    """Estimate the local historical edge for the current strategy pattern."""
    if df is None or len(df) < 120 or not pattern or pattern == "אין דפוס פריצה איכותי כרגע":
        return {
            "success_rate": None,
            "sample_size": 0,
            "avg_forward_return": None,
            "score_adjust": 0,
            "note": "אין מספיק מופעים היסטוריים אמינים לדפוס הזה.",
        }

    work = df.copy().sort_index()
    close = work["close"]
    high = work["high"]
    low = work["low"]
    volume = work["volume"]
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    avg_vol20 = volume.rolling(20).mean()
    rvol = volume / avg_vol20.replace(0, pd.NA)
    prior_high20 = high.rolling(20).max().shift(1)
    prior_high50 = high.rolling(50).max().shift(1)
    prior_high252 = high.rolling(252, min_periods=120).max().shift(1)
    dist20 = (close / prior_high20 - 1.0) * 100.0
    range10 = (high.rolling(10).max() - low.rolling(10).min()) / close
    range30 = (high.rolling(30).max() - low.rolling(30).min()) / close

    if "52" in pattern:
        signal = close.ge(prior_high252 * 0.98) & close.gt(sma50) & rvol.ge(1.0)
        target_pct, stop_pct = 0.10, -0.06
    elif "היפוך" in pattern:
        prior_down = close.shift(35).lt(close.shift(70) * 0.92)
        higher_low = low.rolling(20).min().gt(low.shift(25).rolling(30).min() * 1.03)
        signal = prior_down & higher_low & close.gt(sma20) & (close / sma50 - 1.0).ge(-0.03) & rvol.ge(1.0)
        target_pct, stop_pct = 0.07, -0.05
    elif "Pullback" in pattern or "פולבק" in pattern:
        recent_high = close.rolling(15).max()
        controlled_pullback = (close / recent_high - 1.0).between(-0.08, -0.015)
        near_sma20 = ((close / sma20 - 1.0) * 100).abs().le(3.0)
        signal = close.gt(sma50) & sma20.gt(sma50) & controlled_pullback & near_sma20
        target_pct, stop_pct = 0.06, -0.04
    elif "Reclaim" in pattern or "SMA50" in pattern:
        was_below = close.shift(3).rolling(9).min().lt(sma50)
        signal = was_below & close.gt(sma50) & ((close / sma50 - 1.0) * 100).le(4.0) & rvol.ge(1.0)
        target_pct, stop_pct = 0.07, -0.05
    elif "Dry-Up" in pattern or "Volume Dry" in pattern:
        quiet_volume = volume.rolling(5).mean().lt(volume.shift(5).rolling(20).mean() * 0.75)
        tight_price = range10.lt(range30 * 0.7)
        signal = quiet_volume & tight_price & dist20.ge(-4)
        target_pct, stop_pct = 0.07, -0.045
    elif "התכווצות" in pattern:
        tight_price = range10.lt(range30 * 0.75)
        signal = tight_price & dist20.between(-4, 1) & close.gt(sma20) & rvol.ge(0.7)
        target_pct, stop_pct = 0.07, -0.045
    elif "Cup" in pattern:
        signal = dist20.ge(-2) & close.gt(sma50) & range10.lt(range30 * 0.85) & rvol.ge(0.8)
        target_pct, stop_pct = 0.09, -0.055
    elif "דגל" in pattern or "Bull" in pattern:
        impulse = close.shift(10) / close.shift(20) - 1.0
        pullback = close / close.rolling(5).max() - 1.0
        signal = impulse.gt(0.08) & pullback.between(-0.08, 0.01) & close.gt(sma20) & close.gt(sma50)
        target_pct, stop_pct = 0.08, -0.05
    elif "פריצה מעל שיא 20" in pattern:
        signal = close.ge(prior_high20 * 0.995) & close.gt(sma20) & close.gt(sma50) & rvol.ge(0.8)
        target_pct, stop_pct = 0.075, -0.05
    elif "קרוב לפריצה" in pattern:
        signal = dist20.between(-4, 0.5) & close.gt(sma20) & close.gt(sma50) & rvol.ge(0.7)
        target_pct, stop_pct = 0.065, -0.045
    else:
        signal = dist20.ge(-2) & close.gt(sma20) & close.gt(sma50) & rvol.ge(0.9)
        target_pct, stop_pct = 0.07, -0.05

    # Leave the latest 20 bars out so only completed forward windows are measured.
    signal_indices = [i for i, is_signal in enumerate(signal.fillna(False).tolist()) if is_signal and 80 <= i < len(work) - 20]
    if not signal_indices:
        return {
            "success_rate": None,
            "sample_size": 0,
            "avg_forward_return": None,
            "score_adjust": 0,
            "note": "לא נמצאו מספיק מופעים היסטוריים דומים בתוך הדאטה המקומי.",
        }

    outcomes: list[bool] = []
    forward_returns: list[float] = []
    for i in signal_indices[-80:]:
        entry = float(close.iloc[i])
        if entry <= 0:
            continue
        future = work.iloc[i + 1:i + 21]
        if future.empty:
            continue
        target_price = entry * (1 + target_pct)
        stop_price = entry * (1 + stop_pct)
        hit_target = future["high"].ge(target_price)
        hit_stop = future["low"].le(stop_price)
        target_at = hit_target.idxmax() if bool(hit_target.any()) else None
        stop_at = hit_stop.idxmax() if bool(hit_stop.any()) else None
        success = bool(hit_target.any() and (stop_at is None or target_at <= stop_at))
        outcomes.append(success)
        forward_returns.append(float((future["high"].max() / entry - 1.0) * 100.0))

    sample_size = len(outcomes)
    if sample_size < 3:
        return {
            "success_rate": None,
            "sample_size": sample_size,
            "avg_forward_return": None,
            "score_adjust": 0,
            "note": "נמצאו מעט מדי דגימות דומות כדי להסיק יתרון היסטורי.",
        }

    success_rate = sum(outcomes) / sample_size * 100.0
    avg_forward_return = sum(forward_returns) / sample_size
    if sample_size >= 8 and success_rate >= 62:
        adjust = 5
        label = "היסטורית הדפוס עבד טוב במניה הזו"
    elif sample_size >= 8 and success_rate <= 38:
        adjust = -5
        label = "היסטורית הדפוס חלש במניה הזו"
    elif success_rate >= 55:
        adjust = 2
        label = "יש יתרון היסטורי מתון לדפוס"
    else:
        adjust = 0
        label = "היסטוריית הדפוס ניטרלית"

    return {
        "success_rate": float(success_rate),
        "sample_size": sample_size,
        "avg_forward_return": float(avg_forward_return),
        "score_adjust": adjust,
        "note": f"{label}: {success_rate:.0f}% הצלחה מתוך {sample_size} מופעים, תנועה מקסימלית ממוצעת {avg_forward_return:.1f}% ב-20 ימי מסחר.",
    }


def _bull_flag_candidate(df: pd.DataFrame, snap: IndicatorSnapshot) -> bool:
    if len(df) < 25:
        return False
    close = df["close"]
    impulse = close.iloc[-10] / close.iloc[-20] - 1.0
    pullback = close.iloc[-1] / close.iloc[-5:].max() - 1.0
    return impulse > 0.08 and -0.08 <= pullback <= 0.01 and snap.trend == "uptrend_strong"


def _cup_handle_candidate(df: pd.DataFrame, snap: IndicatorSnapshot) -> bool:
    if len(df) < 80:
        return False
    close = df["close"].tail(80)
    left_high = close.head(20).max()
    middle_low = close.iloc[20:60].min()
    right_high = close.tail(20).max()
    depth = (left_high - middle_low) / left_high if left_high else 0
    recovered = right_high >= left_high * 0.9
    near_high = snap.breakout_dist_50d_pct >= -5
    return 0.12 <= depth <= 0.38 and recovered and near_high


def _trend_reversal_candidate(df: pd.DataFrame, snap: IndicatorSnapshot) -> bool:
    if len(df) < 80:
        return False
    close = df["close"]
    low = df["low"]
    prior_down = close.iloc[-35] < close.iloc[-70] * 0.92
    higher_low = low.tail(20).min() > low.iloc[-55:-25].min() * 1.03
    reclaiming = snap.close > snap.sma20 and snap.dist_from_sma50_pct >= -3
    improving_volume = snap.rvol_20 >= 1.0
    return prior_down and higher_low and reclaiming and improving_volume


def _pullback_to_sma20_candidate(df: pd.DataFrame, snap: IndicatorSnapshot) -> bool:
    if len(df) < 50 or snap.trend != "uptrend_strong":
        return False
    close = df["close"]
    recent_high = close.tail(15).max()
    controlled_pullback = -0.08 <= (snap.close / recent_high - 1.0) <= -0.015
    near_sma20 = abs(snap.dist_from_sma20_pct) <= 3.0
    held_sma20 = df["low"].tail(5).min() >= snap.sma20 * 0.985
    return controlled_pullback and near_sma20 and held_sma20


def _reclaim_sma50_candidate(df: pd.DataFrame, snap: IndicatorSnapshot) -> bool:
    if len(df) < 70:
        return False
    close = df["close"]
    was_below = close.iloc[-12:-3].lt(snap.sma50).any()
    reclaimed = snap.close > snap.sma50 and snap.dist_from_sma50_pct <= 4.0
    return bool(was_below and reclaimed and snap.rvol_20 >= 1.0)


def _fifty_two_week_breakout_candidate(snap: IndicatorSnapshot) -> bool:
    if snap.high_52w is None or snap.high_52w <= 0:
        return False
    dist_52w = (snap.close / snap.high_52w - 1.0) * 100.0
    return dist_52w >= -2.0 and snap.close > snap.sma50 and snap.rvol_20 >= 1.0


def _volume_dry_up_candidate(df: pd.DataFrame, snap: IndicatorSnapshot) -> bool:
    if len(df) < 45:
        return False
    recent_volume = df["volume"].tail(5).mean()
    prior_volume = df["volume"].tail(25).head(20).mean()
    quiet_volume = prior_volume > 0 and recent_volume < prior_volume * 0.75
    tight_price = _has_compression(df)
    near_trigger = snap.breakout_dist_20d_pct >= -4 or abs(snap.dist_from_sma20_pct) <= 3
    return bool(quiet_volume and tight_price and near_trigger)


def _technical_state(df: pd.DataFrame) -> dict[str, Any]:
    if df is None or df.empty or len(df) < 30:
        return {
            "rsi": None,
            "macd_label": "אין דאטה",
            "adx": None,
            "cci": None,
            "score_bonus": 0,
            "reasons": [],
        }
    close = df["close"]
    high = df["high"]
    low = df["low"]

    rsi = _rsi(close).iloc[-1]
    macd_line, signal_line = _macd(close)
    macd_hist = (macd_line - signal_line).iloc[-1]
    adx = _adx(high, low, close).iloc[-1]
    cci = _cci(high, low, close).iloc[-1]

    bonus = 0
    reasons: list[str] = []
    if pd.notna(rsi):
        if 55 <= rsi <= 72:
            bonus += 8
            reasons.append("RSI באזור מומנטום בריא")
        elif rsi > 78:
            bonus -= 6
            reasons.append("RSI גבוה מאוד ולכן יש סיכון לרדיפה")
    if pd.notna(macd_hist) and macd_hist > 0:
        bonus += 7
        reasons.append("MACD תומך במומנטום חיובי")
    if pd.notna(adx) and adx >= 20:
        bonus += 6
        reasons.append("ADX מצביע על מגמה עם עוצמה")
    if pd.notna(cci):
        if 50 <= cci <= 200:
            bonus += 5
            reasons.append("CCI תומך בלחץ קונים")
        elif cci > 250:
            bonus -= 4
            reasons.append("CCI מתוח מדי")

    return {
        "rsi": None if pd.isna(rsi) else float(rsi),
        "macd_label": "חיובי" if pd.notna(macd_hist) and macd_hist > 0 else "שלילי/ניטרלי",
        "adx": None if pd.isna(adx) else float(adx),
        "cci": None if pd.isna(cci) else float(cci),
        "score_bonus": bonus,
        "reasons": reasons,
    }


def _institutional_layer(
    df: pd.DataFrame,
    snap: IndicatorSnapshot,
    setup_score: int,
    level: str,
    pattern: str,
    spy_df: pd.DataFrame | None,
    qqq_df: pd.DataFrame | None,
) -> dict[str, Any]:
    score = 0
    notes: list[str] = []

    rs_spy = _relative_strength_20d(df, spy_df)
    rs_qqq = _relative_strength_20d(df, qqq_df)
    if rs_spy is not None:
        if rs_spy >= 5:
            score += 18
            notes.append("מנצחת את SPY ב-20 יום")
        elif rs_spy >= 0:
            score += 10
            notes.append("חזקה יחסית ל-SPY")
        else:
            score -= 6
            notes.append("חלשה מול SPY")
    if rs_qqq is not None:
        if rs_qqq >= 5:
            score += 14
            notes.append("מנצחת את QQQ ב-20 יום")
        elif rs_qqq >= 0:
            score += 8
            notes.append("חזקה יחסית ל-QQQ")
        else:
            score -= 5
            notes.append("חלשה מול QQQ")

    candle_quality, candle_score, candle_note = _candle_quality(df)
    score += candle_score
    notes.append(candle_note)

    volume_confirmation, volume_score = _volume_confirmation(snap)
    score += volume_score
    notes.append(volume_confirmation)

    if level == "A+ Setup":
        score += 18
    elif level == "Watchlist":
        score += 10
    elif level == "Early Momentum":
        score += 4

    if pattern != "אין דפוס פריצה איכותי כרגע":
        score += 10
    a_plus_min = _score_threshold("SCAN_A_PLUS_MIN_SCORE", 85)
    watch_min = _score_threshold("SCAN_WATCHLIST_MIN_SCORE", 70)
    if setup_score >= a_plus_min:
        score += 12
    elif setup_score >= watch_min:
        score += 8
    elif setup_score >= _score_threshold("SCAN_EARLY_MIN_SCORE", 45):
        score += 4

    score = max(0, min(100, score))
    if score >= 82:
        tag = "מוסדי חזק"
    elif score >= 68:
        tag = "מוסדי בינוני"
    elif score >= 52:
        tag = "מוקדם אבל מעניין"
    else:
        tag = "דורש אישור"

    return {
        "score": int(score),
        "tag": tag,
        "rs_spy_20": rs_spy,
        "rs_qqq_20": rs_qqq,
        "candle_quality": candle_quality,
        "volume_confirmation": volume_confirmation,
        "note": "; ".join(notes) + ".",
    }


def _market_regime(
    spy: IndicatorSnapshot | None,
    qqq: IndicatorSnapshot | None,
    iwm: IndicatorSnapshot | None,
) -> dict[str, Any]:
    items = [("SPY", spy), ("QQQ", qqq), ("IWM", iwm)]
    usable = [(name, snap) for name, snap in items if snap is not None]
    if not usable:
        return {
            "regime": "לא זמין",
            "score": 50,
            "score_adjust": 0,
            "long_support": "לא נבדק",
            "note": "אין מספיק דאטה למדדי השוק.",
        }

    score = 0
    notes: list[str] = []
    for name, snap in usable:
        local = 0
        if snap.close > snap.sma20 > snap.sma50:
            local += 28
            notes.append(f"{name} במגמת עלייה קצרה")
        elif snap.close > snap.sma50:
            local += 18
            notes.append(f"{name} מעל SMA50")
        elif snap.close < snap.sma50:
            local -= 16
            notes.append(f"{name} מתחת SMA50")

        if snap.pct_change_1d > 0:
            local += min(8, int(round(snap.pct_change_1d * 2)))
        if snap.breakout_dist_20d_pct >= -2:
            local += 8
        if snap.atr_ext_above_sma20 > 3:
            local -= 6
        score += local

    normalized = max(0, min(100, int(round(50 + score / max(1, len(usable))))))
    if normalized >= 72:
        regime = "Risk-On / שוק תומך לונג"
        support = "תומך"
        adjust = 6
    elif normalized >= 55:
        regime = "שוק ניטרלי-חיובי"
        support = "תומך חלקית"
        adjust = 2
    elif normalized >= 42:
        regime = "שוק מעורב"
        support = "זהירות"
        adjust = -2
    else:
        regime = "Risk-Off / שוק מסוכן ללונג"
        support = "לא תומך"
        adjust = -8

    return {
        "regime": regime,
        "score": normalized,
        "score_adjust": adjust,
        "long_support": support,
        "note": "מצב שוק: " + "; ".join(notes),
    }


def _sector_strength(
    sector_map: dict[str, str],
    universe: dict[str, pd.DataFrame],
    snapshots: dict[str, IndicatorSnapshot],
) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[tuple[float, bool]]] = {}
    for ticker, sector in sector_map.items():
        if not sector or sector == "לא זמין":
            continue
        df = universe.get(ticker)
        snap = snapshots.get(ticker)
        if df is None or snap is None or len(df) < 21:
            continue
        ret_20d = float((df["close"].iloc[-1] / df["close"].iloc[-21] - 1.0) * 100.0)
        above_sma50 = bool(snap.close > snap.sma50)
        groups.setdefault(sector, []).append((ret_20d, above_sma50))

    raw_rows: list[dict[str, Any]] = []
    for sector, values in groups.items():
        if len(values) < 3:
            continue
        avg_return = sum(v[0] for v in values) / len(values)
        above_pct = sum(1 for _, above in values if above) / len(values) * 100.0
        score = max(0, min(100, int(round(45 + avg_return * 2.0 + (above_pct - 50) * 0.35))))
        raw_rows.append({
            "sector": sector,
            "avg_return_20d": avg_return,
            "above_sma50_pct": above_pct,
            "score": score,
            "count": len(values),
        })

    raw_rows.sort(key=lambda row: row["score"], reverse=True)
    output: dict[str, dict[str, Any]] = {}
    for rank_idx, row in enumerate(raw_rows, start=1):
        if row["score"] >= 72:
            rank = "סקטור מוביל"
            adjust = 6
        elif row["score"] >= 58:
            rank = "סקטור חיובי"
            adjust = 3
        elif row["score"] >= 44:
            rank = "סקטור ניטרלי"
            adjust = 0
        else:
            rank = "סקטור חלש"
            adjust = -5
        note = (
            f"סקטור {row['sector']}: תשואה 20 יום ממוצעת {row['avg_return_20d']:.1f}%, "
            f"{row['above_sma50_pct']:.0f}% מהמניות מעל SMA50, דירוג #{rank_idx}."
        )
        output[row["sector"]] = {
            "avg_return_20d": float(row["avg_return_20d"]),
            "score": int(row["score"]),
            "rank": rank,
            "score_adjust": adjust,
            "note": note,
        }
    return output


def _neutral_sector(sector: str) -> dict[str, Any]:
    return {
        "avg_return_20d": None,
        "score": 50,
        "rank": "לא זמין",
        "score_adjust": 0,
        "note": f"סקטור {sector}: אין מספיק דאטה לחוזק סקטור.",
    }


def _relative_strength_20d(df: pd.DataFrame, benchmark_df: pd.DataFrame | None) -> float | None:
    if benchmark_df is None or len(df) < 21 or len(benchmark_df) < 21:
        return None
    stock_return = df["close"].iloc[-1] / df["close"].iloc[-21] - 1.0
    benchmark_return = benchmark_df["close"].iloc[-1] / benchmark_df["close"].iloc[-21] - 1.0
    return float((stock_return - benchmark_return) * 100.0)


def _candle_quality(df: pd.DataFrame) -> tuple[str, int, str]:
    last = df.iloc[-1]
    daily_range = max(float(last["high"] - last["low"]), 0.01)
    close_position = float((last["close"] - last["low"]) / daily_range)
    upper_wick = float((last["high"] - max(last["open"], last["close"])) / daily_range)
    if close_position >= 0.75 and upper_wick <= 0.25:
        return "נר מוסדי חזק", 16, "סגירה קרובה לגבוה עם זנב עליון קטן"
    if close_position >= 0.55 and upper_wick <= 0.40:
        return "נר תקין", 8, "סגירה סבירה ללא דחייה חריגה"
    if upper_wick > 0.45:
        return "דחייה מהגבוה", -8, "יש זנב עליון שמראה מוכרים באזור הגבוה"
    return "נר חלש", -4, "הסגירה לא מספיק חזקה ביחס לטווח היומי"


def _volume_confirmation(snap: IndicatorSnapshot) -> tuple[str, int]:
    if snap.rvol_20 >= 1.8:
        return "אישור ווליום חזק", 16
    if snap.rvol_20 >= 1.3:
        return "אישור ווליום בינוני", 10
    if snap.rvol_20 >= 0.8:
        return "ווליום תקין אך לא חריג", 4
    return "אין אישור ווליום", -8


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def _macd(close: pd.Series) -> tuple[pd.Series, pd.Series]:
    fast = close.ewm(span=12, adjust=False, min_periods=12).mean()
    slow = close.ewm(span=26, adjust=False, min_periods=26).mean()
    macd_line = fast - slow
    signal_line = macd_line.ewm(span=9, adjust=False, min_periods=9).mean()
    return macd_line, signal_line


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    plus_dm = (high.diff()).where(lambda s: (s > (-low.diff())) & (s > 0), 0.0)
    minus_dm = (-low.diff()).where(lambda s: (s > high.diff()) & (s > 0), 0.0)
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di) * 100
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
    typical = (high + low + close) / 3
    sma = typical.rolling(period, min_periods=period).mean()
    mean_dev = (typical - sma).abs().rolling(period, min_periods=period).mean()
    return (typical - sma) / (0.015 * mean_dev)


def _pattern_name(
    cup: bool,
    flag: bool,
    compression: bool,
    broke_20: bool,
    near_20: bool,
    near_50: bool,
    trend_reversal: bool,
    pullback_20: bool,
    reclaim_50: bool,
    breakout_52w: bool,
    volume_dry_up: bool,
) -> str:
    if breakout_52w:
        return "פריצת שיא 52 שבועות"
    if cup:
        return "Cup & Handle אפשרי"
    if flag:
        return "Bull Flag / המשך מומנטום"
    if pullback_20:
        return "Pullback לממוצע 20"
    if trend_reversal:
        return "היפוך מגמה ללונג"
    if reclaim_50:
        return "Reclaim מעל SMA50"
    if compression and (near_20 or near_50):
        return "התכווצות לפני פריצה"
    if volume_dry_up:
        return "Volume Dry-Up לפני פריצה"
    if broke_20:
        return "פריצה מעל שיא 20 ימים"
    if near_20 or near_50:
        return "קרוב לפריצה"
    return "אין דפוס פריצה איכותי כרגע"


def _breakout_status(snap: IndicatorSnapshot) -> str:
    if snap.breakout_dist_20d_pct >= 0:
        return f"פרצה מעל שיא 20 ימים ב־{snap.breakout_dist_20d_pct:.1f}%"
    if snap.breakout_dist_20d_pct >= -2:
        return f"קרובה לפריצה: {abs(snap.breakout_dist_20d_pct):.1f}% מתחת שיא 20 ימים"
    if snap.breakout_dist_50d_pct >= -3:
        return f"קרובה לשיא 50 ימים: {abs(snap.breakout_dist_50d_pct):.1f}% מתחת"
    return "לא קרובה לפריצה"


def _trend_hebrew(trend: str) -> str:
    return {
        "uptrend_strong": "מגמה עולה חזקה",
        "uptrend_weak": "מגמה עולה חלשה",
        "sideways": "דשדוש",
        "downtrend": "מגמת ירידה",
        "insufficient_data": "אין מספיק דאטה",
    }.get(trend, trend)


def _score_threshold(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if raw.isdigit():
        return int(raw)
    return default


def _level(
    score: int,
    actionable_breakout: bool,
    has_quality_pattern: bool,
    has_volume_context: bool,
    extended: bool,
) -> str:
    a_plus_min = _score_threshold("SCAN_A_PLUS_MIN_SCORE", 85)
    watch_min = _score_threshold("SCAN_WATCHLIST_MIN_SCORE", 70)
    early_min = _score_threshold("SCAN_EARLY_MIN_SCORE", 45)
    if (
        score >= a_plus_min
        and actionable_breakout
        and has_quality_pattern
        and has_volume_context
        and not extended
    ):
        return "A+ Setup"
    if score >= watch_min and has_quality_pattern:
        return "Watchlist"
    if score >= early_min:
        return "Early Momentum"
    return "לא מעניין כרגע"


def _risk_note(score: int, extended: bool, rvol: float) -> str:
    if score >= 75 and not extended:
        return "איכות גבוהה יחסית, עדיין להיכנס רק מעל הטריגר."
    if score >= 60:
        return "מעניין, אבל דורש אישור פריצה ונפח."
    if score >= 45:
        return "מוקדם או לא נקי; עדיף להמתין לאישור נוסף."
    if rvol < 1.0:
        return "אין מספיק ווליום לאישור."
    return "לא מספיק איכותי כרגע."


def _target_plan(
    score: int,
    entry: float,
    stop: float,
    target_1: float,
    snap: IndicatorSnapshot,
) -> dict[str, Any]:
    risk = max(entry - stop, snap.atr14, 0.01)
    atr = max(snap.atr14, 0.01)
    target_2 = entry + 3.0 * risk

    resistance_candidates = [
        ("שיא 20 יום", snap.prior_high_20d),
        ("שיא 50 יום", snap.prior_high_50d),
    ]
    if snap.high_52w is not None:
        resistance_candidates.append(("שיא 52 שבועות", snap.high_52w))
    overhead = [(label, value) for label, value in resistance_candidates if value >= entry * 0.995]
    if overhead:
        label, value = min(overhead, key=lambda item: item[1])
        resistance_zone = f"{label} סביב ${value:.2f}"
    else:
        resistance_zone = f"אין התנגדות קרובה ברורה; לעבוד לפי יעדים ${target_1:.2f} / ${target_2:.2f}"

    target_1_probability = max(35, min(85, score - 8))
    if snap.rvol_20 >= 1.5:
        target_1_probability = min(88, target_1_probability + 5)
    if snap.atr_ext_above_sma20 > 3.0:
        target_1_probability = max(30, target_1_probability - 10)
    target_2_probability = max(20, target_1_probability - 18)

    days_to_target_1 = max(3, int(round((target_1 - entry) / atr * 4)))
    days_to_target_2 = max(days_to_target_1 + 5, int(round((target_2 - entry) / atr * 5)))
    if snap.rvol_20 >= 1.5:
        days_to_target_1 = max(2, int(days_to_target_1 * 0.75))
        days_to_target_2 = max(days_to_target_1 + 4, int(days_to_target_2 * 0.8))
    time_to_targets = f"יעד 1: כ-{days_to_target_1}-{days_to_target_1 + 5} ימי מסחר; יעד 2: כ-{days_to_target_2}-{days_to_target_2 + 10} ימי מסחר"

    profit_take_plan = (
        f"לממש 30%-50% באזור יעד 1 (${target_1:.2f}); "
        f"להעלות סטופ לאזור כניסה/ממוצע 20; יתרה ליעד 2 (${target_2:.2f}) כל עוד המומנטום נשמר."
    )

    return {
        "target_2": target_2,
        "resistance_zone": resistance_zone,
        "profit_take_plan": profit_take_plan,
        "target_1_probability": int(target_1_probability),
        "target_2_probability": int(target_2_probability),
        "time_to_targets": time_to_targets,
    }


def _daily_sparkline(df: pd.DataFrame, bars: int = 80) -> str:
    values = df["close"].tail(max(10, bars)).round(2).tolist()
    return json.dumps(values)


def _weekly_sparkline(df: pd.DataFrame) -> str:
    if df.empty:
        return "[]"
    weekly_close = df["close"].resample("W-FRI").last().dropna()
    values = weekly_close.tail(80).round(2).tolist()
    return json.dumps(values)


def _round_or_blank(value: float | None) -> float | str:
    return "" if value is None else round(float(value), 2)
