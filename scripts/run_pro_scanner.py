#!/usr/bin/env python3
"""Run the Hebrew professional long-only scanner."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.analytics.indicators import compute_snapshot
from src.config import load_settings, ensure_directories
from src.data import get_provider
from src.pro_long_scanner import write_professional_long_report


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def _load_fixed_universe(settings) -> list[str]:
    tickers: list[str] = []
    for list_name in settings.active_universe_lists:
        raw = settings.universe_raw.get(list_name, []) or []
        tickers.extend(str(t).upper().strip() for t in raw)
    seen: set[str] = set()
    return [t for t in tickers if t and not (t in seen or seen.add(t))]


def _load_csv_universe(path: Path) -> list[str]:
    df = pd.read_csv(path)
    symbol_col = "symbol" if "symbol" in df.columns else df.columns[0]
    tickers = [str(t).upper().strip() for t in df[symbol_col].dropna()]
    seen: set[str] = set()
    return [t for t in tickers if t and not (t in seen or seen.add(t))]


def _load_sector_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    if not {"symbol", "sector"}.issubset(df.columns):
        return {}
    return {
        str(row["symbol"]).upper().strip(): str(row["sector"]).strip()
        for _, row in df.dropna(subset=["symbol"]).iterrows()
        if str(row["symbol"]).strip()
    }


def _attach_hourly_charts(report: pd.DataFrame, provider, top_n: int, end: date, log: logging.Logger) -> pd.DataFrame:
    if top_n <= 0 or not hasattr(provider, "get_hourly_bars") or "סימבול" not in report.columns:
        return report
    report = report.copy()
    if "גרף שעתי" not in report.columns:
        report["גרף שעתי"] = "[]"

    start = end - timedelta(days=30)
    symbols = report["סימבול"].astype(str).str.upper().head(top_n).tolist()
    for idx, symbol in enumerate(symbols, start=1):
        try:
            hourly = provider.get_hourly_bars(symbol, start, end)
        except Exception as exc:
            log.warning("Failed hourly chart for %s: %s", symbol, exc)
            continue
        if hourly.empty:
            continue
        values = hourly["close"].tail(120).round(2).tolist()
        report.loc[report["סימבול"].astype(str).str.upper() == symbol, "גרף שעתי"] = json.dumps(values)
        if idx % 10 == 0 or idx == len(symbols):
            log.info("Fetched hourly charts %d/%d", idx, len(symbols))
    return report


def _news_catalyst_from_text(text: str) -> tuple[str, int]:
    lowered = text.lower()
    catalyst_rules = [
        ("FDA / ביוטק", 18, ["fda", "clinical trial", "phase 1", "phase 2", "phase 3", "drug approval"]),
        ("דוחות / Earnings", 14, ["earnings", "revenue", "eps", "guidance", "profit"]),
        ("אנליסטים", 10, ["upgrade", "downgrade", "price target", "analyst", "initiated"]),
        ("חוזה / עסקה", 12, ["contract", "partnership", "deal", "agreement", "award"]),
        ("M&A", 12, ["acquisition", "merger", "buyout", "takeover"]),
        ("מוצר / השקה", 8, ["launch", "product", "platform", "patent"]),
    ]
    matches: list[str] = []
    score = 50
    for label, bonus, keywords in catalyst_rules:
        if any(keyword in lowered for keyword in keywords):
            matches.append(label)
            score += bonus
    if any(word in lowered for word in ["beats", "raises", "approval", "upgrade", "surges", "wins"]):
        score += 8
    if any(word in lowered for word in ["misses", "cuts", "investigation", "lawsuit", "warning", "downgrade"]):
        score -= 12
    if not matches:
        matches.append("חדשות כלליות")
    return " + ".join(matches[:3]), max(0, min(100, score))


def _published_date(news_item: dict) -> str:
    published = str(news_item.get("published_utc") or "")
    return published[:10] if published else ""


def _attach_news(report: pd.DataFrame, provider, top_n: int, log: logging.Logger) -> pd.DataFrame:
    if top_n <= 0 or not hasattr(provider, "get_ticker_news") or "סימבול" not in report.columns:
        return report
    report = report.copy()
    for column, default in {
        "חדשות אחרונות": "",
        "ציון חדשות": "",
        "קטליסט": "",
        "תאריך חדשות": "",
    }.items():
        if column not in report.columns:
            report[column] = default
    for column in ["חדשות אחרונות", "קטליסט", "תאריך חדשות"]:
        report[column] = report[column].fillna("").astype("object")

    symbols = report["סימבול"].astype(str).str.upper().head(top_n).tolist()
    for idx, symbol in enumerate(symbols, start=1):
        try:
            news_items = provider.get_ticker_news(symbol, limit=5)
        except Exception as exc:
            log.warning("Failed news fetch for %s: %s", symbol, exc)
            continue
        matching_items = [
            item for item in news_items
            if symbol in [str(t).upper().strip() for t in (item.get("tickers") or [])]
        ]
        if not matching_items:
            continue
        latest = matching_items[0]
        title = str(latest.get("title") or "").strip()
        description = str(latest.get("description") or "").strip()
        catalyst, score = _news_catalyst_from_text(f"{title} {description}")
        if symbol not in title.upper():
            score = min(score, 55)
            catalyst = f"{catalyst} / כתבה רחבה"
        mask = report["סימבול"].astype(str).str.upper() == symbol
        report.loc[mask, "חדשות אחרונות"] = title[:220]
        report.loc[mask, "ציון חדשות"] = score
        report.loc[mask, "קטליסט"] = catalyst
        report.loc[mask, "תאריך חדשות"] = _published_date(latest)
        if idx % 10 == 0 or idx == len(symbols):
            log.info("Fetched news %d/%d", idx, len(symbols))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Professional Hebrew long-only scanner")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--universe-csv", type=Path, default=None, help="CSV with a symbol column")
    parser.add_argument("--output-suffix", type=str, default="", help="Optional suffix before _report.csv")
    parser.add_argument("--sector-map", type=Path, default=ROOT / "data" / "universe" / "sector_map.csv")
    parser.add_argument("--intraday-top", type=int, default=50, help="Fetch hourly charts for top N ranked symbols")
    parser.add_argument("--news-top", type=int, default=100, help="Fetch Polygon news for top N ranked symbols")
    args = parser.parse_args()

    settings = load_settings()
    ensure_directories(settings)
    _setup_logging(settings.log_level)
    log = logging.getLogger("run_pro_scanner")

    provider = get_provider(settings)
    tickers = _load_csv_universe(args.universe_csv) if args.universe_csv else _load_fixed_universe(settings)
    sector_map = _load_sector_map(args.sector_map)
    if args.limit:
        tickers = tickers[:args.limit]

    end = date.today()
    start = end - timedelta(days=int(settings.data.history_years * 365.25))
    universe: dict[str, pd.DataFrame] = {}
    snapshots = {}

    fetch_tickers = tickers.copy()
    for benchmark in ["SPY", "QQQ", "IWM"]:
        if benchmark not in fetch_tickers:
            fetch_tickers.append(benchmark)

    log.info("Starting professional scanner: provider=%s universe=%d", settings.provider, len(tickers))
    for idx, ticker in enumerate(fetch_tickers, start=1):
        try:
            df = provider.get_daily_bars(ticker, start, end)
        except Exception as exc:
            log.warning("Failed to fetch %s: %s", ticker, exc)
            continue
        if df.empty:
            continue
        snap = compute_snapshot(df)
        if snap is None:
            continue
        universe[ticker] = df
        snapshots[ticker] = snap
        if idx % 10 == 0 or idx == len(fetch_tickers):
            log.info("Fetched %d/%d symbols (%d usable)", idx, len(fetch_tickers), len(snapshots))

    filename = settings.reporting.csv_filename_format.format(date=end.isoformat())
    if args.output_suffix:
        filename = filename.replace("_report.csv", f"_{args.output_suffix}_report.csv")
    out = settings.reporting.output_dir / filename
    write_professional_long_report(tickers, universe, snapshots, out, sector_map=sector_map)
    report = pd.read_csv(out)
    report = _attach_hourly_charts(report, provider, args.intraday_top, end, log)
    report = _attach_news(report, provider, args.news_top, log)
    report.to_csv(out, index=False, encoding="utf-8")

    print(f"scanner_status=ok")
    print(f"provider={settings.provider}")
    print(f"symbols_requested={len(tickers)}")
    print(f"symbols_with_usable_data={len(snapshots)}")
    print(f"report_file={out.name}")
    print(f"report_rows={len(report)}")
    print(f"top_setups={(report['רמה'].isin(['A+ Setup', 'Watchlist', 'Early Momentum'])).sum()}")
    print("levels=" + str(report["רמה"].value_counts(dropna=False).to_dict()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
