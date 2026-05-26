#!/usr/bin/env python3
"""Run the Hebrew professional long-only scanner."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.analytics.indicators import compute_snapshot
from src.config import load_settings, ensure_directories
from src.data import get_provider
from src.pro_long_scanner import write_professional_long_report
from src.scan_profiles import ScanProfile, apply_profile_to_env, get_profile
from src.data.base import ProviderError
from src.scan_progress import clear_progress, write_progress


def _validate_profile_thresholds(
    report: pd.DataFrame,
    profile: ScanProfile | None,
    log: logging.Logger,
) -> None:
    if profile is None or "הסתברות %" not in report.columns or "רמה" not in report.columns:
        return
    a_plus = report[report["רמה"] == "A+ Setup"]
    if a_plus.empty:
        print(f"threshold_violations=0")
        print(f"a_plus_min_enforced={profile.a_plus_min_score}")
        return
    scores = pd.to_numeric(a_plus["הסתברות %"], errors="coerce")
    violations = int((scores < profile.a_plus_min_score).sum())
    print(f"threshold_violations={violations}")
    print(f"a_plus_min_enforced={profile.a_plus_min_score}")
    if violations:
        log.error(
            "Profile %s: %d A+ rows below minimum score %d",
            profile.id,
            violations,
            profile.a_plus_min_score,
        )


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


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _default_workers() -> int:
    from src.scan_runtime import cap_scan_workers, is_render_host

    explicit = os.getenv("SCAN_WORKERS", "").strip()
    if explicit.isdigit() and int(explicit) > 0:
        return cap_scan_workers(int(explicit))
    if is_render_host():
        return cap_scan_workers(2)
    provider = os.getenv("DATA_PROVIDER", "demo").lower()
    cpu = os.cpu_count() or 4
    if os.getenv("SPACE_ID"):
        return cap_scan_workers(8 if provider in {"demo", "tiingo"} else 4)
    return min(32, max(4, cpu * 2))


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


def _fetch_symbol(
    ticker: str,
    provider,
    start: date,
    end: date,
    *,
    trim_bars: int | None,
) -> tuple[str, pd.DataFrame | None, Any | None]:
    try:
        df = provider.get_daily_bars(ticker, start, end)
    except ProviderError as exc:
        msg = str(exc)
        if "401" in msg or "Unknown API Key" in msg or "API Key" in msg:
            raise RuntimeError(
                "מפתח נתוני שוק לא תקין (401). עדכן את מפתח ה-API ב-Render Environment."
            ) from exc
        return ticker, None, None
    except Exception:
        return ticker, None, None
    if df is None or df.empty:
        return ticker, None, None
    if trim_bars and len(df) > trim_bars:
        df = df.tail(trim_bars).copy()
    snap = compute_snapshot(df)
    if snap is None:
        return ticker, None, None
    return ticker, df, snap


def _polygon_bulk_enabled(provider) -> bool:
    if not hasattr(provider, "load_universe_daily_bars"):
        return False
    raw = os.getenv("SCAN_POLYGON_BULK", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _load_universe_bulk(
    fetch_tickers: list[str],
    provider,
    start: date,
    end: date,
    trim_bars: int | None,
    log: logging.Logger,
    *,
    universe_size: int,
    profile_id: str = "",
    profile_label: str = "",
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    from src.analytics.indicators import compute_snapshot

    universe: dict[str, pd.DataFrame] = {}
    snapshots: dict[str, Any] = {}
    total_days = len(pd.bdate_range(start=pd.Timestamp(start), end=pd.Timestamp(end)))
    label = profile_label or "סריקה"

    def on_day(done_days: int, total_session_days: int) -> None:
        stocks_done = min(
            universe_size,
            int(universe_size * done_days / max(total_session_days, 1)),
        )
        pct = 5 + int(70 * done_days / max(total_session_days, 1))
        write_progress(
            pct,
            "טעינת נתונים",
            done=stocks_done,
            total=universe_size,
            message=f"{label}: Polygon מרוכז {done_days}/{total_session_days} ימי מסחר",
            profile_id=profile_id,
            profile_label=profile_label,
        )

    log.info("Polygon bulk load: %d symbols, ~%d session days", len(fetch_tickers), total_days)
    raw = provider.load_universe_daily_bars(fetch_tickers, start, end, on_progress=on_day)
    done = 0
    for ticker in fetch_tickers:
        df = raw.get(ticker.upper().strip())
        if df is None or df.empty:
            continue
        if trim_bars and len(df) > trim_bars:
            df = df.tail(trim_bars).copy()
        snap = compute_snapshot(df)
        if snap is None:
            continue
        universe[ticker] = df
        snapshots[ticker] = snap
        done += 1
        if done == 1 or done % 200 == 0 or done >= universe_size:
            pct = 5 + int(70 * min(done, universe_size) / max(universe_size, 1))
            write_progress(
                pct,
                "טעינת נתונים",
                done=min(done, universe_size),
                total=universe_size,
                message=f"{label}: נטענו {min(done, universe_size):,} מתוך {universe_size:,} מניות",
                profile_id=profile_id,
                profile_label=profile_label,
            )
    log.info("Polygon bulk load finished: %d/%d usable", len(snapshots), len(fetch_tickers))
    return universe, snapshots


def _load_universe_parallel(
    fetch_tickers: list[str],
    provider,
    start: date,
    end: date,
    workers: int,
    trim_bars: int | None,
    log: logging.Logger,
    *,
    universe_size: int,
    profile_id: str = "",
    profile_label: str = "",
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    if _polygon_bulk_enabled(provider) and len(fetch_tickers) >= 80:
        try:
            return _load_universe_bulk(
                fetch_tickers,
                provider,
                start,
                end,
                trim_bars,
                log,
                universe_size=universe_size,
                profile_id=profile_id,
                profile_label=profile_label,
            )
        except Exception as exc:
            log.warning("Bulk Polygon load failed; falling back to per-symbol: %s", exc)

    universe: dict[str, pd.DataFrame] = {}
    snapshots: dict[str, Any] = {}
    total = len(fetch_tickers)
    done = 0
    symbol_timeout = int(os.getenv("SCAN_SYMBOL_TIMEOUT", "90") or "90")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fetch_symbol, ticker, provider, start, end, trim_bars=trim_bars): ticker
            for ticker in fetch_tickers
        }
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                ticker, df, snap = future.result(timeout=symbol_timeout)
            except FuturesTimeoutError:
                log.warning("Timeout loading %s after %ss", ticker, symbol_timeout)
                done += 1
                continue
            except Exception as exc:
                log.warning("Failed loading %s: %s", ticker, exc)
                done += 1
                continue
            done += 1
            if df is not None and snap is not None:
                universe[ticker] = df
                snapshots[ticker] = snap
            if done == 1 or done % 100 == 0 or done == total:
                stocks_done = min(done, universe_size)
                log.info(
                    "Loaded %d/%d universe stocks (%d usable)",
                    stocks_done,
                    universe_size,
                    len(snapshots),
                )
                pct = 5 + int(70 * stocks_done / max(universe_size, 1))
                label = profile_label or "סריקה"
                write_progress(
                    pct,
                    "טעינת נתונים",
                    done=stocks_done,
                    total=universe_size,
                    message=f"{label}: נטענו {stocks_done:,} מתוך {universe_size:,} מניות",
                    profile_id=profile_id,
                    profile_label=profile_label,
                )
    return universe, snapshots


def main() -> int:
    parser = argparse.ArgumentParser(description="Professional Hebrew long-only scanner")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--universe-csv", type=Path, default=None, help="CSV with a symbol column")
    parser.add_argument("--output-suffix", type=str, default="", help="Optional suffix before _report.csv")
    parser.add_argument("--sector-map", type=Path, default=ROOT / "data" / "universe" / "sector_map.csv")
    parser.add_argument("--intraday-top", type=int, default=None, help="Fetch hourly charts for top N ranked symbols")
    parser.add_argument("--news-top", type=int, default=None, help="Fetch Polygon news for top N ranked symbols")
    parser.add_argument(
        "--fast",
        action="store_true",
        default=None,
        help="Parallel load + skip heavy per-ticker backtest (recommended)",
    )
    parser.add_argument(
        "--enriched",
        action="store_true",
        help="After scan: hourly charts (50) + news (100) — adds ~30-60s",
    )
    parser.add_argument("--workers", type=int, default=None, help="Parallel loader threads (default: auto)")
    parser.add_argument(
        "--profile",
        choices=["simple", "medium", "full"],
        default=None,
        help="Scan depth: simple (fast) | medium (balanced) | full (deepest)",
    )
    args = parser.parse_args()
    write_progress(1, "מתחיל", message="טוען הגדרות סריקה…")

    profile = None
    if args.profile or os.getenv("SCAN_PROFILE"):
        profile = get_profile(args.profile)
        apply_profile_to_env(profile)
        fast = profile.fast_parallel
        args.intraday_top = profile.intraday_top if args.intraday_top is None else args.intraday_top
        args.news_top = profile.news_top if args.news_top is None else args.news_top
        trim_bars = profile.trim_bars
        if not args.output_suffix:
            args.output_suffix = profile.output_suffix
    else:
        fast = args.fast if args.fast is not None else _env_bool("SCAN_FAST", True)
        enriched = args.enriched or _env_bool("SCAN_ENRICHED", False)
        if args.intraday_top is None:
            args.intraday_top = 50 if enriched else 0
        if args.news_top is None:
            args.news_top = 100 if enriched else 0
        trim_bars = 320 if fast else None
        if fast:
            os.environ["SCAN_SKIP_BACKTEST"] = "1"
        trim_env = os.getenv("SCAN_TRIM_BARS", "").strip()
        if trim_env.isdigit():
            trim_bars = int(trim_env)

    workers = args.workers or _default_workers()

    settings = load_settings()
    ensure_directories(settings)
    _setup_logging(settings.log_level)
    log = logging.getLogger("run_pro_scanner")

    write_progress(2, "מתחיל", message=f"ספק נתונים: {settings.provider}")
    try:
        provider = get_provider(settings)
    except RuntimeError as exc:
        log.error("%s", exc)
        clear_progress()
        print("scanner_status=error")
        print(f"error_message={exc}")
        return 1
    tickers = _load_csv_universe(args.universe_csv) if args.universe_csv else _load_fixed_universe(settings)
    sector_map = _load_sector_map(args.sector_map)
    if args.limit:
        tickers = tickers[:args.limit]

    end = date.today()
    if trim_bars:
        start = end - timedelta(days=max(int(trim_bars * 1.6) + 40, 200))
    else:
        start = end - timedelta(days=int(settings.data.history_years * 365.25))
    universe: dict[str, pd.DataFrame] = {}
    snapshots = {}

    fetch_tickers = tickers.copy()
    for benchmark in ["SPY", "QQQ", "IWM"]:
        if benchmark not in fetch_tickers:
            fetch_tickers.append(benchmark)

    profile_id = profile.id if profile else ("fast" if fast else "legacy")
    profile_label = profile.label_he if profile else "סריקה"
    universe_count = len(tickers)
    log.info(
        "Starting professional scanner: provider=%s universe=%d profile=%s workers=%d "
        "intraday=%d news=%d",
        settings.provider,
        len(tickers),
        profile_id,
        workers,
        args.intraday_top,
        args.news_top,
    )
    write_progress(
        3,
        "מתחיל",
        done=0,
        total=universe_count,
        message=f"{profile_label}: מתחיל סריקת {universe_count:,} מניות",
        profile_id=profile_id,
        profile_label=profile_label,
    )
    universe, snapshots = _load_universe_parallel(
        fetch_tickers,
        provider,
        start,
        end,
        workers,
        trim_bars,
        log,
        universe_size=universe_count,
        profile_id=profile_id,
        profile_label=profile_label,
    )

    write_progress(
        78,
        "דירוג",
        done=universe_count,
        total=universe_count,
        message=f"{profile_label}: מדרג {universe_count:,} מניות",
        profile_id=profile_id,
        profile_label=profile_label,
    )

    filename = settings.reporting.csv_filename_format.format(date=end.isoformat())
    if args.output_suffix:
        filename = filename.replace("_report.csv", f"_{args.output_suffix}_report.csv")
    out = settings.reporting.output_dir / filename
    write_professional_long_report(tickers, universe, snapshots, out, sector_map=sector_map)
    write_progress(
        88,
        "דוח",
        done=universe_count,
        total=universe_count,
        message=f"{profile_label}: בונה דוח…",
        profile_id=profile_id,
        profile_label=profile_label,
    )
    report = pd.read_csv(out)
    write_progress(
        92,
        "העשרה",
        done=universe_count,
        total=universe_count,
        message=f"{profile_label}: העשרה (גרפים/חדשות לפי רמה)",
        profile_id=profile_id,
        profile_label=profile_label,
    )
    report = _attach_hourly_charts(report, provider, args.intraday_top, end, log)
    report = _attach_news(report, provider, args.news_top, log)
    _validate_profile_thresholds(report, profile, log)
    write_progress(
        100,
        "הושלם",
        done=universe_count,
        total=universe_count,
        message=f"{profile_label}: הסריקה הסתיימה",
        profile_id=profile_id,
        profile_label=profile_label,
    )
    report.to_csv(out, index=False, encoding="utf-8")

    print("scanner_status=ok")
    print(f"scan_profile={profile_id}")
    print(f"workers={workers}")
    print(f"intraday_top={args.intraday_top}")
    print(f"news_top={args.news_top}")
    print(f"provider={settings.provider}")
    print(f"symbols_requested={len(tickers)}")
    print(f"symbols_with_usable_data={len(snapshots)}")
    print(f"report_file={out.name}")
    print(f"report_rows={len(report)}")
    print(f"top_setups={(report['רמה'].isin(['A+ Setup', 'Watchlist', 'Early Momentum'])).sum()}")
    print("levels=" + str(report["רמה"].value_counts(dropna=False).to_dict()))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        import traceback

        traceback.print_exc()
        print(f"scanner_status=error")
        print(f"error={exc}")
        raise SystemExit(1) from exc
