"""
Main pipeline orchestrator.

Group F changes:
- Threads a DiagnosticsCollector through scanners
- Splits scored signals into MAIN report vs REJECTED CSV based on
  configurable thresholds + active report_mode
- Generates 4 outputs per run:
    1. CSV main report   (qualifying signals)
    2. CSV rejected      (everything else, with rejection reasons)
    3. Text summary      (human-readable)
    4. Text diagnostics  (rejection counts and stage breakdown)
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import pandas as pd

from src.config import DATA_DIR, Settings, ensure_directories
from src.data import get_provider, DataProvider
from src.data.base import SymbolMetadata
from src.analytics.indicators import compute_snapshot, IndicatorSnapshot
from src.analytics.market_regime import classify_market_regime, MarketRegime
from src.strategies import build_strategies
from src.strategies.base import SetupSignal, STATUS_IGNORE, STATUS_TRIGGER, STATUS_WATCH
from src.scanners import build_scanners
from src.scoring import ScoreEngine, ScoredSignal
from src.reporting import print_summary, save_summary
from src.reporting.csv_report import generate_csv_report, generate_rejected_csv
from src.pro_long_scanner import write_professional_long_report
from src.diagnostics import (
    DiagnosticsCollector,
    REASON_GENERIC_NOT_ACTIONABLE,
    REASON_DOWNGRADED_TO_WAIT,
    REASON_LOW_RVOL,
    REASON_MISSING_ACTION_PLAN,
    REASON_SCORE_BELOW_THRESHOLD,
)


log = logging.getLogger(__name__)

CONTINUATION_WATCH_MIN_SCORE = 65
CONTINUATION_WATCH_MIN_RVOL = 1.0
MIN_ACTIONABLE_RISK_REWARD = 1.8


def _load_universe_tickers(settings: Settings) -> list[str]:
    """Load the ticker list based on universe mode.

    full_liquid_us_stocks: reads from data/universe/final_universe.csv
    starter: reads from universe.yaml hand-picked lists
    """
    from src.universe import load_final_universe

    mode = settings.universe_cfg.mode

    if mode == "full_liquid_us_stocks":
        tickers = load_final_universe(settings)
        if not tickers:
            log.warning("final_universe.csv empty or missing. Falling back to starter mode.")
            mode = "starter"
        else:
            log.info("Universe mode: full_liquid_us_stocks (%d tickers)", len(tickers))
            return tickers

    # Starter mode
    raw = settings.universe_raw
    active_lists = settings.active_universe_lists
    exclude_set: set[str] = set()
    always_exclude = raw.get("always_exclude", []) or []
    exclude_set.update(t.upper().strip() for t in always_exclude)

    tickers: list[str] = []
    seen: set[str] = set()
    for list_name in active_lists:
        symbols = raw.get(list_name, [])
        if not isinstance(symbols, list):
            log.warning("Universe list '%s' is not a list, skipping.", list_name)
            continue
        for sym in symbols:
            s = sym.upper().strip()
            if s and s not in seen and s not in exclude_set:
                tickers.append(s)
                seen.add(s)

    log.info("Universe mode: starter (%d tickers)", len(tickers))
    return tickers


def _load_universe_metadata(settings: Settings) -> dict[str, SymbolMetadata]:
    """Load static metadata from final_universe.csv when using the full universe."""
    if settings.universe_cfg.mode != "full_liquid_us_stocks":
        return {}

    final_path = DATA_DIR / "universe" / settings.universe_cfg.file_final
    if not final_path.exists():
        return {}

    try:
        df = pd.read_csv(final_path)
    except Exception as exc:
        log.warning("Could not read universe metadata from %s: %s", final_path, exc)
        return {}

    required = {"symbol", "exchange", "asset_type"}
    if not required.issubset(df.columns):
        return {}

    metadata: dict[str, SymbolMetadata] = {}
    for row in df.to_dict("records"):
        symbol = str(row.get("symbol", "")).strip().upper()
        if not symbol:
            continue
        metadata[symbol] = SymbolMetadata(
            symbol=symbol,
            exchange=str(row.get("exchange", "")).strip().upper() or "UNKNOWN",
            asset_type=str(row.get("asset_type", "")).strip().lower() or "unknown",
            name=str(row.get("name", "")).strip() or None,
            is_active=True,
        )

    return metadata


def _fetch_universe_data(
    tickers: list[str],
    provider: DataProvider,
    history_years: int,
) -> dict[str, pd.DataFrame]:
    """Fetch OHLCV for all tickers.

    Uses the provider's bulk load when available (Polygon grouped daily),
    otherwise falls back to parallel per-symbol fetching.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import os

    end = date.today()
    start = end - timedelta(days=int(history_years * 365.25))

    if hasattr(provider, "load_universe_daily_bars") and len(tickers) >= 80:
        try:
            raw = provider.load_universe_daily_bars(tickers, start, end)
            universe: dict[str, pd.DataFrame] = {}
            for sym in tickers:
                df = raw.get(sym.upper().strip())
                if df is not None and not df.empty and len(df) >= 50:
                    universe[sym] = df
            log.info("Bulk load: %d/%d tickers usable", len(universe), len(tickers))
            return universe
        except Exception as exc:
            log.warning("Bulk load failed, falling back to parallel per-symbol: %s", exc)

    try:
        workers = max(1, int(os.getenv("SCAN_WORKERS", "4")))
    except ValueError:
        workers = 4
    workers = min(workers, 16)

    universe = {}

    def _fetch_one(sym: str) -> tuple[str, pd.DataFrame | None]:
        try:
            df = provider.get_daily_bars(sym, start, end)
            if not df.empty and len(df) >= 50:
                return sym, df
        except Exception as exc:
            log.warning("Failed to fetch %s: %s", sym, exc)
        return sym, None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_one, sym): sym for sym in tickers}
        for future in as_completed(futures):
            try:
                sym, df = future.result(timeout=120)
                if df is not None:
                    universe[sym] = df
            except Exception as exc:
                log.warning("Fetch timeout/error for %s: %s", futures[future], exc)

    return universe


def _compute_snapshots(
    universe: dict[str, pd.DataFrame],
) -> dict[str, IndicatorSnapshot]:
    """Compute indicator snapshots for all tickers."""
    snapshots: dict[str, IndicatorSnapshot] = {}
    for sym, df in universe.items():
        snap = compute_snapshot(df)
        if snap is not None:
            snapshots[sym] = snap
    return snapshots


def _build_fallback_regime() -> MarketRegime:
    """Build a placeholder regime when SPY/QQQ aren't in universe."""
    from src.analytics.market_regime import (
        MarketRegime, TREND_SIDEWAYS, VOL_NORMAL,
    )
    return MarketRegime(
        as_of=pd.Timestamp.now(),
        trend_label=TREND_SIDEWAYS,
        volatility_label=VOL_NORMAL,
        composite_label="Unknown (SPY/QQQ not available)",
        spy_close=0, spy_sma50=0, spy_sma200=None,
        spy_pct_above_sma50=0, spy_pct_above_sma200=None,
        spy_sma50_slope_pct=0,
        qqq_close=0, qqq_sma50=0, qqq_pct_above_sma50=0,
        qqq_sma50_slope_pct=0, qqq_agrees_with_spy=True,
        vix_close=None, realized_vol_annualized_pct=0,
        confidence=0,
    )


def _watchlist_quality_rejection(
    scored: ScoredSignal,
    snapshot: IndicatorSnapshot | None,
    settings: Settings,
) -> tuple[str, str] | None:
    """Return a rejection reason when a scored setup is too generic for reports."""
    sig = scored.signal

    def _is_missing(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, (int, float)):
            return value <= 0
        return False

    def _missing(*fields: str) -> tuple[str, str]:
        return (
            REASON_MISSING_ACTION_PLAN,
            "missing required action-plan fields: " + ", ".join(fields),
        )

    def _generic(detail: str) -> tuple[str, str]:
        return (REASON_GENERIC_NOT_ACTIONABLE, detail)

    if sig.status not in {STATUS_TRIGGER, STATUS_WATCH}:
        return (
            REASON_DOWNGRADED_TO_WAIT,
            f"status {sig.status!r} is not eligible for main/watchlist reports",
        )

    required_values = {
        "entry_trigger": sig.entry_trigger,
        "stop_loss": sig.stop_loss,
        "target_1": sig.target_1,
        "risk_reward": sig.risk_reward,
        "invalidation": sig.invalidation,
        "what_to_wait_for": sig.wait_for,
    }
    missing = [name for name, value in required_values.items() if _is_missing(value)]
    if missing:
        return _missing(*missing)

    if sig.risk_reward < MIN_ACTIONABLE_RISK_REWARD:
        return _generic(
            f"risk_reward {sig.risk_reward:.1f} < {MIN_ACTIONABLE_RISK_REWARD:.1f} actionable gate"
        )

    if sig.scanner_mode in {"pre_breakout", "breakout"} and sig.status == STATUS_WATCH:
        breakout_level = sig.factor_inputs.get("prior_high") or sig.factor_inputs.get("breakout_level")
        if snapshot is None or not breakout_level:
            return _missing("breakout_level", "distance_to_breakout_pct")
        distance_to_breakout_pct = (float(breakout_level) / snapshot.close - 1.0) * 100.0
        if distance_to_breakout_pct < 0 or distance_to_breakout_pct > 1.5:
            return _generic(
                f"distance_to_breakout_pct {distance_to_breakout_pct:.2f}% outside 0-1.5% near-trigger gate",
            )

    if sig.scanner_mode == "breakout" and sig.status == STATUS_TRIGGER:
        breakout_level = sig.factor_inputs.get("prior_high") or sig.factor_inputs.get("breakout_level")
        if not breakout_level:
            return _missing("breakout_level")
        rvol = float(sig.factor_inputs.get("rvol", snapshot.rvol_20 if snapshot else 0.0))
        lookback = int(sig.factor_inputs.get("lookback", 20) or 20)
        min_rvol = settings.volume.rvol_min_breakout if lookback != 20 else settings.thresholds.min_relative_volume
        if rvol < min_rvol:
            return _generic(f"confirmed breakout RVOL {rvol:.1f}x < {min_rvol:.1f}x")

    if sig.scanner_mode == "continuation" and sig.status == STATUS_WATCH:
        fi = sig.factor_inputs
        has_clear_pattern = bool(
            fi.get("flagpole_pct")
            or fi.get("prior_leg_pct")
            or fi.get("reversal_candle")
        )
        if not has_clear_pattern:
            return _missing("clear_continuation_pattern")
        if not sig.wait_for.strip():
            return _missing("clear_condition_to_wait_for")
        if scored.final_score < CONTINUATION_WATCH_MIN_SCORE:
            return _generic(
                f"continuation score {scored.final_score} < {CONTINUATION_WATCH_MIN_SCORE} quality gate"
            )
        if snapshot is not None and snapshot.rvol_20 < CONTINUATION_WATCH_MIN_RVOL:
            return _generic(
                f"continuation RVOL {snapshot.rvol_20:.1f}x < {CONTINUATION_WATCH_MIN_RVOL:.1f}x quality gate"
            )

    return None


def run_pipeline(settings: Settings, limit: int | None = None) -> dict[str, Any]:
    """Execute the full daily pipeline.

    Args:
        settings: Settings object
        limit:    optional cap on the number of tickers to process (for testing)

    Returns:
        dict with scored_signals (main), watchlist_signals, rejected_signals,
        paths to all output files, and a stats dict.
    """
    ensure_directories(settings)

    # --- 1. Init ---
    diag = DiagnosticsCollector()
    provider = get_provider(settings)
    strategies = build_strategies(settings.strategies_raw)
    scanners = build_scanners(strategies, settings, diagnostics=diag)
    score_engine = ScoreEngine(settings.scoring)

    log.info("Mode: %s | main≥%d | watch≥%d",
             settings.report_mode.active,
             settings.report_mode.main_report_score,
             settings.report_mode.watchlist_score)

    # --- 2. Universe ---
    tickers = _load_universe_tickers(settings)
    metadata_by_ticker = _load_universe_metadata(settings)
    log.info("Universe: %d tickers", len(tickers))

    # Apply limit (for testing / --limit flag)
    if limit is not None and limit > 0 and len(tickers) > limit:
        log.info("Limit applied: scanning first %d of %d tickers", limit, len(tickers))
        tickers = tickers[:limit]

    # --- 3. Fetch + snapshots ---
    universe = _fetch_universe_data(tickers, provider, settings.data.history_years)
    snapshots = _compute_snapshots(universe)
    diag.set_universe_stats(
        size=len(tickers),
        fetched=len(universe),
        snapshots_built=len(snapshots),
    )

    # --- 4. Market regime ---
    spy_df = universe.get("SPY")
    qqq_df = universe.get("QQQ")
    if spy_df is not None and qqq_df is not None:
        regime = classify_market_regime(spy_df, qqq_df)
    else:
        log.warning("SPY or QQQ missing — using fallback regime")
        regime = _build_fallback_regime()

    # --- 4b. Liquidity filter (Group G) — runs BEFORE scanners ---
    from src.liquidity import run_liquidity_filter
    liquidity_results = run_liquidity_filter(
        tickers=list(universe.keys()),
        universe=universe,
        snapshots=snapshots,
        provider=provider,
        settings=settings,
        diag=diag,
        metadata_by_ticker=metadata_by_ticker,
    )
    # Only liquid tickers get scanned
    liquid_tickers = set(liquidity_results.keys())
    universe_filtered = {sym: universe[sym] for sym in liquid_tickers if sym in universe}
    log.info("Liquidity filter passed: %d/%d tickers", len(liquid_tickers), len(universe))

    # --- 5. Run scanners (on LIQUID universe only) ---
    # Performance: reuse precomputed snapshots so scanners don't recompute them.
    # Progress: print every 50 tickers.
    all_signals: list[SetupSignal] = []
    total_to_scan = len(universe_filtered)

    def _make_progress(scanner_name: str):
        def _cb(idx: int, total: int, ticker: str) -> None:
            if idx % 50 == 0 or idx == total:
                log.info("  [%s] %d / %d tickers scanned", scanner_name, idx, total)
        return _cb

    for scanner in scanners:
        scanner_name = type(scanner).__name__
        log.info("Running scanner: %s (%d tickers)", scanner_name, total_to_scan)
        signals = scanner.scan_universe(
            universe_filtered,
            snapshots=snapshots,
            progress_callback=_make_progress(scanner_name),
        )
        all_signals.extend(signals)
        log.info("  [%s] produced %d signals", scanner_name, len(signals))
    log.info("Total signals: %d", len(all_signals))

    # --- 6. Score ---
    scored_all = score_engine.score_batch(all_signals, snapshots)

    # --- 7. Split by threshold (Group I: three-tier reporting) ---
    min_main = settings.report_mode.main_report_score
    min_watch = settings.report_mode.watchlist_score

    main_signals: list[ScoredSignal] = []
    watchlist_signals: list[ScoredSignal] = []
    rejected_signals: list[ScoredSignal] = []

    for s in scored_all:
        snap = snapshots.get(s.signal.ticker)
        quality_rejection = _watchlist_quality_rejection(s, snap, settings)

        if quality_rejection is None and s.final_score >= min_main:
            main_signals.append(s)
            diag.mark_in_main_report(s.signal.ticker)
        elif quality_rejection is None and s.final_score >= min_watch:
            watchlist_signals.append(s)
        else:
            reason_code, detail = quality_rejection or (
                REASON_SCORE_BELOW_THRESHOLD,
                f"final score {s.final_score} < main threshold {min_main}",
            )
            if quality_rejection is not None:
                s.signal.warnings.append(f"{reason_code}: {detail}")
                if s.signal.status == STATUS_WATCH:
                    s.signal.status = STATUS_IGNORE
            rejected_signals.append(s)
            diag.mark_in_rejected_csv(s.signal.ticker)
            # Log the reason
            diag.record(
                ticker=s.signal.ticker,
                reason_code=reason_code,
                detail=detail,
                strategy=s.signal.strategy_module,
                snapshot_summary="",
                score=s.final_score,
            )

    log.info("Main report: %d | Watchlist: %d | Rejected: %d (main≥%d, watch≥%d)",
             len(main_signals), len(watchlist_signals), len(rejected_signals),
             min_main, min_watch)

    # --- 8. Generate three-tier report outputs ---
    run_date = date.today()

    # 8a. Main Report CSV
    csv_path = generate_csv_report(
        scored_signals=main_signals,
        snapshots=snapshots,
        regime=regime,
        output_dir=settings.reporting.output_dir,
        run_date=run_date,
        filename_format=settings.reporting.csv_filename_format,
        liquidity_results=liquidity_results,
        scanned_tickers=tickers,
        all_scored_signals=scored_all,
    )
    write_professional_long_report(
        tickers=tickers,
        universe=universe,
        snapshots=snapshots,
        output_path=csv_path,
    )

    # 8b. Watchlist CSV
    from src.reporting.watchlist_report import generate_watchlist_csv
    watchlist_path = generate_watchlist_csv(
        scored_signals=watchlist_signals,
        snapshots=snapshots,
        output_dir=settings.reporting.output_dir,
        main_score_threshold=min_main,
        run_date=run_date,
        filename_format=settings.reporting.watchlist_filename_format,
        liquidity_results=liquidity_results,
    )

    # 8c. Rejected CSV
    rejected_path = generate_rejected_csv(
        scored_signals=rejected_signals,
        snapshots=snapshots,
        output_dir=settings.reporting.output_dir,
        run_date=run_date,
        filename_format=settings.reporting.rejected_filename_format,
    )

    # 8d. Summary
    summary_text = print_summary(
        scored_signals=main_signals,
        watchlist_signals=watchlist_signals,
        rejected_signals=rejected_signals,
        snapshots=snapshots,
        regime=regime,
        universe_size=len(tickers),
        passed_liquidity=len(liquid_tickers),    # Group J fix: use the actual liquidity-passed count
        run_date=run_date,
        main_report_count=len(main_signals),
        watchlist_count=len(watchlist_signals),
        rejected_count=len(rejected_signals),
        report_mode=settings.report_mode.active,
        main_threshold=min_main,
        watchlist_threshold=min_watch,
        diagnostics=diag,
        raw_signal_total=len(all_signals),
    )

    summary_path = save_summary(
        summary_text=summary_text,
        output_dir=settings.reporting.output_dir,
        run_date=run_date,
        filename_format=settings.reporting.summary_filename_format,
    )

    # 8e. Mark watchlist tickers in diagnostics
    for s in watchlist_signals:
        diag.mark_in_watch_only(s.signal.ticker)

    # Diagnostics: text + detail CSV
    diagnostics_path = diag.save_text_report(
        output_dir=settings.reporting.output_dir,
        run_date=run_date,
        filename_format=settings.reporting.diagnostics_filename_format,
    )

    return {
        "scored_signals": main_signals,
        "watchlist_signals": watchlist_signals,
        "rejected_signals": rejected_signals,
        "regime": regime,
        "diagnostics": diag,
        "csv_path": csv_path,
        "watchlist_path": watchlist_path,
        "rejected_path": rejected_path,
        "summary_path": summary_path,
        "diagnostics_path": diagnostics_path,
        "stats": {
            "universe_size": len(tickers),
            "fetched": len(universe),
            "snapshots_built": len(snapshots),
            "passed_liquidity_filter": len(liquid_tickers),
            "total_signals": len(all_signals),
            "main_report": len(main_signals),
            "watchlist": len(watchlist_signals),
            "rejected": len(rejected_signals),
            "report_mode": settings.report_mode.active,
            "main_score_threshold": min_main,
            "watchlist_score_threshold": min_watch,
        },
        "liquidity_results": liquidity_results,
    }
