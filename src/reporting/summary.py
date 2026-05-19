"""
Terminal summary builder.

Group I: prints Main Report + Watchlist + Rejected counts, 5 score bands,
rejection categories, and the standard trade-plan fields per setup.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from src.scoring.score_engine import ScoredSignal
from src.analytics.indicators import IndicatorSnapshot
from src.analytics.market_regime import MarketRegime


# Colors
G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; C = "\033[96m"; B = "\033[1m"; W = "\033[0m"
DIM = "\033[2m"

STATUS_COLORS = {
    "Watch": Y, "Trigger": G, "Wait for pullback": C,
    "Ignore": DIM, "Invalidated": R,
}


def print_summary(
    scored_signals: list[ScoredSignal],
    snapshots: dict[str, IndicatorSnapshot],
    regime: MarketRegime,
    universe_size: int,
    passed_liquidity: int,
    run_date: date | None = None,
    watchlist_signals: list[ScoredSignal] | None = None,
    rejected_signals: list[ScoredSignal] | None = None,
    main_report_count: int | None = None,
    watchlist_count: int | None = None,
    rejected_count: int = 0,
    report_mode: str = "balanced",
    main_threshold: int = 75,
    watchlist_threshold: int = 60,
    diagnostics: Any = None,            # DiagnosticsCollector or None
    raw_signal_total: int | None = None,
) -> str:
    """Print daily summary and return as text. Group I three-tier layout."""
    run_date = run_date or date.today()
    watchlist_signals = watchlist_signals or []
    rejected_signals  = rejected_signals  or []
    lines: list[str] = []

    def out(line: str = "") -> None:
        lines.append(line)
        print(line)

    # ---- Header ----
    out(f"\n{B}{C}{'='*72}{W}")
    out(f"{B}{C}  MOMENTUM DECISION-SUPPORT SYSTEM — Daily Report{W}")
    out(f"{B}{C}  {run_date.isoformat()}   ·   Mode: {report_mode}{W}")
    out(f"{B}{C}{'='*72}{W}")
    out()

    # ---- Market regime ----
    regime_color = G if regime.trend_label == "uptrend" else (R if regime.trend_label == "downtrend" else Y)
    out(f"  {B}Market Regime:{W}  {regime_color}{regime.composite_label}{W}")
    out(f"  SPY ${regime.spy_close:.2f} ({regime.spy_pct_above_sma50:+.1f}% vs SMA50)  "
        f"QQQ ${regime.qqq_close:.2f} ({regime.qqq_pct_above_sma50:+.1f}% vs SMA50)")
    favorable = regime.is_favorable_for_long_momentum()
    out(f"  Favorable for long momentum: {G + 'Yes' + W if favorable else R + 'No — be very selective' + W}")
    out()

    # ---- Three-tier counts ----
    if main_report_count is None:
        main_report_count = len(scored_signals)
    if watchlist_count is None:
        watchlist_count = len(watchlist_signals)
    if raw_signal_total is None:
        raw_signal_total = main_report_count + watchlist_count + rejected_count

    out(f"  {B}Scan Statistics:{W}")
    out(f"  Universe scanned:          {universe_size}")
    out(f"  Passed liquidity filter:   {passed_liquidity}")
    out(f"  Total raw signals:         {raw_signal_total}")
    out()
    out(f"  {B}Three-Tier Report:{W}")
    out(f"  {G}Main Report (score >= {main_threshold}):       {main_report_count}{W}")
    out(f"  {Y}Watchlist (score {watchlist_threshold}-{main_threshold-1}):           {watchlist_count}{W}")
    out(f"  {DIM}Rejected (score < {watchlist_threshold}):           {rejected_count}{W}")
    out()

    # ---- 5 score bands ----
    all_scored: list[ScoredSignal] = list(scored_signals) + list(watchlist_signals) + list(rejected_signals)
    band_90_plus  = sum(1 for s in all_scored if s.final_score >= 90)
    band_85_89    = sum(1 for s in all_scored if 85 <= s.final_score < 90)
    band_75_84    = sum(1 for s in all_scored if 75 <= s.final_score < 85)
    band_60_74    = sum(1 for s in all_scored if 60 <= s.final_score < 75)
    band_below_60 = sum(1 for s in all_scored if s.final_score < 60)

    out(f"  {B}Score Distribution:{W}")
    out(f"    {G}90+ (elite):       {band_90_plus:>5}{W}")
    out(f"    {G}85-89 (strong):    {band_85_89:>5}{W}")
    out(f"    {Y}75-84 (good):      {band_75_84:>5}{W}")
    out(f"    {Y}60-74 (watchlist): {band_60_74:>5}{W}")
    out(f"    {DIM}below 60:          {band_below_60:>5}{W}")
    out()

    # ---- Rejection categories (Group I requirement) ----
    if diagnostics is not None:
        out(f"  {B}Rejection Categories:{W}")
        for label, count in diagnostics.summary_by_category().items():
            color = (R if count > 0 else DIM)
            out(f"    {color}{label:30}{W}  {count:>5}")
        out()

        # Top rejection reasons
        out(f"  {B}Top 5 Rejection Reasons:{W}")
        from src.diagnostics import REASON_LABELS
        for code, count in diagnostics.by_reason().most_common(5):
            label = REASON_LABELS.get(code, code)
            out(f"    {count:>5}  {label}")
        out()

    # ---- Status distribution ----
    by_status: dict[str, int] = {}
    for s in scored_signals + watchlist_signals:
        by_status[s.signal.status] = by_status.get(s.signal.status, 0) + 1

    if by_status:
        out(f"  {B}Status Distribution (Main + Watchlist):{W}")
        for status_name in ["Trigger", "Watch", "Wait for pullback", "Ignore", "Invalidated"]:
            count = by_status.get(status_name, 0)
            if count:
                clr = STATUS_COLORS.get(status_name, W)
                out(f"    {clr}{status_name:22s}{W}: {count}")
        out()

    # ---- Main Report listings ----
    if not scored_signals:
        out(f"  {Y}MAIN REPORT: No setups scored above {main_threshold} today.{W}")
        out(f"  {DIM}This is normal — the system is selective by design.{W}")
        if watchlist_signals:
            out(f"  {DIM}Check the WATCHLIST below ({len(watchlist_signals)} candidates "
                f"in {watchlist_threshold}-{main_threshold-1} range).{W}")
        out()
    else:
        out(f"  {B}{G}MAIN REPORT — Strong Candidates ({len(scored_signals)} setups):{W}")
        out(f"  {B}{'Rank':>4}  {'Score':>5}  {'Status':22}  {'Ticker':6}  "
            f"{'Setup':30}  {'R/R':>5}  {'Entry':>8}  {'Stop':>8}  {'T1':>8}{W}")
        out(f"  {'-'*120}")
        for i, scored in enumerate(scored_signals):
            sig = scored.signal
            clr = STATUS_COLORS.get(sig.status, W)
            out(f"  {i+1:>4}  {scored.final_score:>5}  "
                f"{clr}{sig.status:22}{W}  {sig.ticker:6}  "
                f"{sig.setup_type:30}  {sig.risk_reward:>5.1f}  "
                f"${sig.entry_trigger:>7.2f}  ${sig.stop_loss:>7.2f}  ${sig.target_1:>7.2f}")
        out()

    # ---- Watchlist preview ----
    if watchlist_signals:
        preview = watchlist_signals[:10]
        out(f"  {B}{Y}WATCHLIST — NOT TRADE-READY — top {len(preview)} of {len(watchlist_signals)}:{W}")
        out(f"  {DIM}WATCH ONLY / LOWER CONFIDENCE / NEEDS CONFIRMATION{W}")
        out(f"  {B}{'Rank':>4}  {'Score':>5}  {'Status':22}  {'Ticker':6}  "
            f"{'Setup':30}  {'R/R':>5}{W}")
        out(f"  {'-'*100}")
        for i, scored in enumerate(preview):
            sig = scored.signal
            clr = STATUS_COLORS.get(sig.status, W)
            out(f"  {i+1:>4}  {scored.final_score:>5}  "
                f"{clr}{sig.status:22}{W}  {sig.ticker:6}  "
                f"{sig.setup_type:30}  {sig.risk_reward:>5.1f}")
        out()

    # ---- Detail cards for top 5 Main Report setups ----
    top_n = scored_signals[:5]
    if top_n:
        out(f"  {B}Detail — Top {len(top_n)} Main Report setups:{W}")
        for idx, scored in enumerate(top_n):
            sig = scored.signal
            snap = snapshots.get(sig.ticker)
            clr = STATUS_COLORS.get(sig.status, W)

            out(f"\n  {B}#{idx+1} {sig.ticker}{W}  Score: {scored.final_score}  "
                f"{clr}{sig.status}{W}")
            out(f"    Setup:            {sig.setup_type} ({sig.scanner_mode})")
            if snap:
                out(f"    Price:            ${snap.close:.2f}  (today {snap.pct_change_1d:+.1f}%)")
                out(f"    RVOL:             {snap.rvol_20:.1f}x  |  Dollar vol: ${snap.dollar_volume_20:,.0f}")
                out(f"    Trend:            {snap.trend}  |  Dist SMA20: {snap.dist_from_sma20_pct:+.1f}%  "
                    f"|  ATR ext: {snap.atr_ext_above_sma20:.1f}x")
            # The 7 required trade-plan fields
            out(f"    entry_trigger:    ${sig.entry_trigger:.2f}")
            out(f"    stop_loss:        ${sig.stop_loss:.2f}")
            out(f"    target_1:         ${sig.target_1:.2f}")
            out(f"    target_2:         ${sig.target_2:.2f}")
            out(f"    risk_reward:      {sig.risk_reward:.1f}")
            out(f"    invalidation:     {sig.invalidation}")
            out(f"    what_to_wait_for: {sig.wait_for}")
            out(f"    Reason:           {sig.reason[:120]}")
            if sig.warnings:
                for warn in sig.warnings:
                    out(f"    {Y}⚠ {warn}{W}")

    out(f"\n{C}{'='*72}{W}")
    if watchlist_count > 0:
        out(f"  {DIM}{watchlist_count} watchlist candidates → see *_watchlist.csv (NOT trade-ready){W}")
    if rejected_count > 0:
        out(f"  {DIM}{rejected_count} rejected → see *_rejected.csv and *_diagnostics.txt{W}")
    out(f"  {DIM}{'-'*68}{W}")
    out(f"  {DIM}This is a decision-support tool. It does not recommend trades.{W}")
    out(f"  {DIM}Every setup requires your own analysis before considering entry.{W}")
    out(f"{C}{'='*72}{W}\n")

    return "\n".join(lines)


def save_summary(
    summary_text: str,
    output_dir: Path,
    run_date: date | None = None,
    filename_format: str = "{date}_summary.txt",
) -> Path:
    """Save the summary as a text file (strips ANSI escape codes)."""
    import re
    run_date = run_date or date.today()
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = filename_format.format(date=run_date.isoformat())
    filepath = output_dir / filename
    clean = re.sub(r'\033\[[0-9;]*m', '', summary_text)
    filepath.write_text(clean, encoding="utf-8")
    return filepath
