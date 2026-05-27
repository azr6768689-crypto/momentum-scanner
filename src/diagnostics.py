"""
Diagnostics collector.

Tracks why candidates were rejected at every stage of the pipeline.

Design:
- A single DiagnosticsCollector instance threads through the whole run.
- Each rejection records: ticker, stage, reason_code, detail, snapshot values.
- At the end of the run, we can aggregate to:
    "How many failed at each stage?"
    "How many failed for each reason?"
    "Per-ticker rejection trail."

This is read-only inspection — it never changes behavior. It exists so the
user can SEE what the system is filtering and decide if filters are right.
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path
from typing import Any


# =============================================================================
# Standardized rejection reason codes
# =============================================================================
# Use these everywhere instead of free-text. Free text in `detail` is fine
# for human display, but `reason_code` must be from this list so we can count.

# Stage 1 — Liquidity gates
REASON_LIQUIDITY_PRICE        = "liquidity_price_below_min"
REASON_LIQUIDITY_VOLUME       = "liquidity_avg_volume_below_min"
REASON_LIQUIDITY_DOLLAR       = "liquidity_dollar_volume_below_min"

# Stage 2 — Data availability
REASON_INSUFFICIENT_BARS      = "insufficient_bars"
REASON_NO_DATA                = "no_data_returned"

# Stage 3 — Strategy-level (no pattern detected)
REASON_NO_PATTERN             = "no_pattern_matched"
REASON_STRATEGY_DISABLED      = "strategy_disabled"

# Stage 4 — Trend filter
REASON_TREND_DOWNTREND        = "trend_downtrend"
REASON_TREND_INSUFFICIENT     = "trend_insufficient_data"
REASON_BELOW_SMA50            = "close_below_sma50"

# Stage 5 — Volume filter
REASON_LOW_RVOL               = "rvol_below_min"
REASON_VOLUME_NOT_CONFIRMED   = "volume_not_confirming"

# Stage 6 — Risk/reward filter
REASON_LOW_RR                 = "risk_reward_below_min"
REASON_RESISTANCE_TOO_CLOSE   = "next_resistance_too_close"

# Stage 7 — Extension filter
REASON_EXTENDED_ATR           = "extended_above_sma20_atr"
REASON_EXTENDED_PCT           = "extended_above_sma20_pct"
REASON_DAY_GAIN_TOO_HIGH      = "day_gain_too_high_no_setup"
REASON_EXHAUSTION_CANDLE      = "exhaustion_candle"

# Stage 8 — Score filter
REASON_SCORE_BELOW_THRESHOLD  = "score_below_threshold"

# Stage 9 — Scanner-level downgrades (not full rejections, but worth tracking)
REASON_DOWNGRADED_TO_WAIT     = "downgraded_to_wait_for_pullback"
REASON_DOWNGRADED_TO_IGNORE   = "downgraded_to_ignore"

# Other
REASON_REMAINING_UPSIDE_LOW   = "remaining_upside_too_low"
REASON_MISSING_ACTION_PLAN    = "missing_action_plan_fields"
REASON_GENERIC_NOT_ACTIONABLE = "generic_signal_not_actionable"
REASON_OTHER                  = "other"


# Human-readable labels for the diagnostics report
REASON_LABELS: dict[str, str] = {
    REASON_LIQUIDITY_PRICE:       "Price below minimum",
    REASON_LIQUIDITY_VOLUME:      "Average volume below minimum",
    REASON_LIQUIDITY_DOLLAR:      "Dollar volume below minimum",
    REASON_INSUFFICIENT_BARS:     "Not enough historical bars",
    REASON_NO_DATA:               "Provider returned no data",
    REASON_NO_PATTERN:            "No strategy pattern matched",
    REASON_STRATEGY_DISABLED:     "Strategy disabled in config",
    REASON_TREND_DOWNTREND:       "Stock is in a downtrend",
    REASON_TREND_INSUFFICIENT:    "Insufficient trend data",
    REASON_BELOW_SMA50:           "Close below SMA50 (weak trend)",
    REASON_LOW_RVOL:              "Relative volume below required threshold",
    REASON_VOLUME_NOT_CONFIRMED:  "Volume not confirming the move",
    REASON_LOW_RR:                "Risk/reward below minimum",
    REASON_RESISTANCE_TOO_CLOSE:  "Next resistance too close to entry",
    REASON_EXTENDED_ATR:          "Too extended above SMA20 (ATR-based)",
    REASON_EXTENDED_PCT:          "Too extended above SMA20 (%-based)",
    REASON_DAY_GAIN_TOO_HIGH:     "Day gain too high without clean setup",
    REASON_EXHAUSTION_CANDLE:     "Exhaustion candle (close in bottom of range)",
    REASON_SCORE_BELOW_THRESHOLD: "Score below minimum threshold",
    REASON_DOWNGRADED_TO_WAIT:    "Status downgraded to 'Wait for pullback'",
    REASON_DOWNGRADED_TO_IGNORE:  "Status downgraded to 'Ignore'",
    REASON_REMAINING_UPSIDE_LOW:  "Remaining upside too low (too late)",
    REASON_MISSING_ACTION_PLAN:   "Missing required action-plan fields",
    REASON_GENERIC_NOT_ACTIONABLE:"Generic signal is not actionable",
    REASON_OTHER:                 "Other",
}


# Stage groupings (for the aggregated report)
STAGE_OF_REASON: dict[str, str] = {
    REASON_LIQUIDITY_PRICE:       "1_liquidity",
    REASON_LIQUIDITY_VOLUME:      "1_liquidity",
    REASON_LIQUIDITY_DOLLAR:      "1_liquidity",
    REASON_INSUFFICIENT_BARS:     "2_data",
    REASON_NO_DATA:               "2_data",
    REASON_NO_PATTERN:            "3_strategy_no_match",
    REASON_STRATEGY_DISABLED:     "3_strategy_disabled",
    REASON_TREND_DOWNTREND:       "4_trend",
    REASON_TREND_INSUFFICIENT:    "4_trend",
    REASON_BELOW_SMA50:           "4_trend",
    REASON_LOW_RVOL:              "5_volume",
    REASON_VOLUME_NOT_CONFIRMED:  "5_volume",
    REASON_LOW_RR:                "6_risk_reward",
    REASON_RESISTANCE_TOO_CLOSE:  "6_risk_reward",
    REASON_EXTENDED_ATR:          "7_extension",
    REASON_EXTENDED_PCT:          "7_extension",
    REASON_DAY_GAIN_TOO_HIGH:     "7_extension",
    REASON_EXHAUSTION_CANDLE:     "7_extension",
    REASON_SCORE_BELOW_THRESHOLD: "8_score",
    REASON_DOWNGRADED_TO_WAIT:    "9_downgrade",
    REASON_DOWNGRADED_TO_IGNORE:  "9_downgrade",
    REASON_REMAINING_UPSIDE_LOW:  "6_risk_reward",
    REASON_MISSING_ACTION_PLAN:   "8_score",
    REASON_GENERIC_NOT_ACTIONABLE:"8_score",
    REASON_OTHER:                 "0_other",
}


@dataclass
class RejectionRecord:
    """One rejection event."""
    ticker: str
    stage: str               # e.g. "1_liquidity"
    reason_code: str         # one of the REASON_* constants
    detail: str              # human-readable specifics
    strategy: str = ""       # which strategy raised it (empty for stage 1/2)
    snapshot_summary: str = ""   # short string of key stats
    score: int | None = None     # final score if rejection happened post-scoring


_MAX_RECORDS = 5000
_NO_PATTERN_SAMPLE_RATE = 10


class DiagnosticsCollector:
    """Threadsafe-ish collector of rejection events.

    Phase 1 is single-threaded so we don't bother with locks, but the dict
    structure is append-only so adding locking later is trivial.

    To prevent memory explosion on large universes (3000+ tickers × 3
    scanners × 2 strategies = 18K+ records), ``no_pattern_matched`` events
    are sampled (1 in 10) and aggregate counts are always maintained.
    """

    def __init__(self) -> None:
        self.records: list[RejectionRecord] = []
        self._reason_counts: Counter[str] = Counter()
        self._stage_counts: Counter[str] = Counter()
        self._strategy_reason_counts: Counter[tuple[str, str]] = Counter()
        # Universe-level facts (set once per run)
        self.universe_size: int = 0
        self.fetched: int = 0
        self.snapshots_built: int = 0
        # Counter of tickers that DID make it to the final report
        self.tickers_in_main_report: set[str] = set()
        self.tickers_in_watch_only: set[str] = set()
        self.tickers_in_rejected_csv: set[str] = set()
        self._no_pattern_counter: int = 0

    # -- Recording --------------------------------------------------------

    def record(
        self,
        ticker: str,
        reason_code: str,
        detail: str = "",
        strategy: str = "",
        snapshot_summary: str = "",
        score: int | None = None,
    ) -> None:
        """Record one rejection event.

        Counts are always updated.  Individual records are capped at
        ``_MAX_RECORDS``, and ``no_pattern_matched`` events are sampled
        1-in-N to avoid 18K+ records on large universes.
        """
        stage = STAGE_OF_REASON.get(reason_code, "0_other")
        self._reason_counts[reason_code] += 1
        self._stage_counts[stage] += 1
        if strategy:
            self._strategy_reason_counts[(strategy, reason_code)] += 1

        if reason_code == REASON_NO_PATTERN:
            self._no_pattern_counter += 1
            if self._no_pattern_counter % _NO_PATTERN_SAMPLE_RATE != 1:
                return

        if len(self.records) >= _MAX_RECORDS:
            return

        self.records.append(RejectionRecord(
            ticker=ticker,
            stage=stage,
            reason_code=reason_code,
            detail=detail,
            strategy=strategy,
            snapshot_summary=snapshot_summary,
            score=score,
        ))

    # -- Universe stats ---------------------------------------------------

    def set_universe_stats(self, size: int, fetched: int, snapshots_built: int) -> None:
        self.universe_size = size
        self.fetched = fetched
        self.snapshots_built = snapshots_built

    def mark_in_main_report(self, ticker: str) -> None:
        self.tickers_in_main_report.add(ticker)

    def mark_in_watch_only(self, ticker: str) -> None:
        self.tickers_in_watch_only.add(ticker)

    def mark_in_rejected_csv(self, ticker: str) -> None:
        self.tickers_in_rejected_csv.add(ticker)

    # -- Aggregation ------------------------------------------------------

    def by_reason(self) -> Counter[str]:
        """Count rejections per reason code (uses exact counters, not sampled records)."""
        return Counter(self._reason_counts)

    def by_stage(self) -> Counter[str]:
        """Count rejections per stage (uses exact counters, not sampled records)."""
        return Counter(self._stage_counts)

    def by_ticker(self) -> dict[str, list[RejectionRecord]]:
        """All rejections grouped by ticker."""
        result: dict[str, list[RejectionRecord]] = defaultdict(list)
        for r in self.records:
            result[r.ticker].append(r)
        return dict(result)

    def by_strategy_and_reason(self) -> dict[tuple[str, str], int]:
        """Count rejections per (strategy, reason) (exact counts)."""
        return dict(self._strategy_reason_counts)

    def summary_by_category(self) -> dict[str, int]:
        """Group rejections into the user-facing categories for the summary.

        Returns a dict like:
            {
                "Score too low":          138,
                "Risk/reward too low":     13,
                "Overextended":            42,
                "Weak trend":               5,
                "Weak volume":              0,
                "Moved to Wait for pullback": 55,
            }
        """
        by_r = self.by_reason()
        score_too_low = (
            by_r.get(REASON_SCORE_BELOW_THRESHOLD, 0)
        )
        rr_too_low = (
            by_r.get(REASON_LOW_RR, 0)
            + by_r.get(REASON_RESISTANCE_TOO_CLOSE, 0)
            + by_r.get(REASON_REMAINING_UPSIDE_LOW, 0)
        )
        overextended = (
            by_r.get(REASON_EXTENDED_ATR, 0)
            + by_r.get(REASON_EXTENDED_PCT, 0)
            + by_r.get(REASON_DAY_GAIN_TOO_HIGH, 0)
            + by_r.get(REASON_EXHAUSTION_CANDLE, 0)
        )
        weak_trend = (
            by_r.get(REASON_TREND_DOWNTREND, 0)
            + by_r.get(REASON_TREND_INSUFFICIENT, 0)
            + by_r.get(REASON_BELOW_SMA50, 0)
        )
        weak_volume = (
            by_r.get(REASON_LOW_RVOL, 0)
            + by_r.get(REASON_VOLUME_NOT_CONFIRMED, 0)
        )
        moved_to_wait = (
            by_r.get(REASON_DOWNGRADED_TO_WAIT, 0)
        )
        return {
            "Score too low":              score_too_low,
            "Risk/reward too low":        rr_too_low,
            "Overextended":               overextended,
            "Weak trend":                 weak_trend,
            "Weak volume":                weak_volume,
            "Moved to Wait for pullback": moved_to_wait,
        }

    # -- Writing the diagnostics report -----------------------------------

    def render_text_report(self, run_date: date | None = None) -> str:
        """Build a human-readable text diagnostics report."""
        run_date = run_date or date.today()
        lines: list[str] = []

        def w(line: str = "") -> None:
            lines.append(line)

        w("=" * 72)
        w(f"  DIAGNOSTICS REPORT — {run_date.isoformat()}")
        w("=" * 72)
        w()

        # --- Universe pipeline ---
        w("UNIVERSE PIPELINE")
        w("-" * 40)
        w(f"  Tickers in universe:           {self.universe_size}")
        w(f"  Tickers with data fetched:     {self.fetched}")
        w(f"  Snapshots successfully built:  {self.snapshots_built}")
        w(f"  Tickers in MAIN report:        {len(self.tickers_in_main_report)}")
        w(f"  Tickers in WATCHLIST:          {len(self.tickers_in_watch_only)}")
        w(f"  Tickers in rejected CSV:       {len(self.tickers_in_rejected_csv)}")
        w(f"  Total rejection events logged: {len(self.records)}")
        w()

        # --- By high-level category (Group I) ---
        w("REJECTIONS BY CATEGORY")
        w("-" * 40)
        for label, count in self.summary_by_category().items():
            w(f"  {label:30}  {count:>5}")
        w()

        # --- By stage ---
        w("REJECTIONS BY STAGE")
        w("-" * 40)
        by_stage = self.by_stage()
        for stage, count in sorted(by_stage.items()):
            stage_name = stage.split("_", 1)[1] if "_" in stage else stage
            w(f"  {stage:18}  {count:>5}   ({stage_name})")
        w()

        # --- By reason (the headline section) ---
        w("REJECTIONS BY REASON  (highest first)")
        w("-" * 40)
        by_reason = self.by_reason()
        for reason_code, count in by_reason.most_common():
            label = REASON_LABELS.get(reason_code, reason_code)
            w(f"  {count:>5}   {reason_code:35}  {label}")
        w()

        # --- By strategy + reason ---
        strat_rejections = self.by_strategy_and_reason()
        if strat_rejections:
            w("STRATEGY-LEVEL REJECTIONS")
            w("-" * 40)
            # Group by strategy
            by_strat: dict[str, list[tuple[str, int]]] = defaultdict(list)
            for (strat, reason), count in strat_rejections.items():
                by_strat[strat].append((reason, count))
            for strat in sorted(by_strat.keys()):
                w(f"  {strat}:")
                for reason, count in sorted(by_strat[strat], key=lambda x: -x[1]):
                    label = REASON_LABELS.get(reason, reason)
                    w(f"      {count:>4}   {label}")
                w()

        # --- Interpretation hints ---
        w("INTERPRETATION")
        w("-" * 40)
        w("  - High counts in stage 1 (liquidity)? Universe contains illiquid names.")
        w("  - High counts in stage 4 (trend)? Market regime may be unfavorable.")
        w("  - High counts in stage 5 (volume)? RVOL threshold may be too strict")
        w("    OR the market simply has low volume today.")
        w("  - High counts in stage 6 (R/R)? Strategy entries are too late or")
        w("    targets are too conservative. Consider adjusting target multipliers.")
        w("  - High counts in stage 7 (extension)? Stocks are running fast and")
        w("    pulling back hasn't happened yet — wait for a pullback day.")
        w("  - High counts in stage 8 (score)? Many setups are 'OK but not great' —")
        w("    consider exploratory mode to see them, or wait for better setups.")
        w()
        w("  To see lower-quality candidates, set:")
        w("      report_mode.active: exploratory   in config/settings.yaml")
        w("  This is for INSPECTION only — exploratory setups are not")
        w("  recommendations and will be clearly labelled as low-confidence.")
        w()
        w("=" * 72)
        return "\n".join(lines)

    def save_text_report(
        self,
        output_dir: Path,
        run_date: date | None = None,
        filename_format: str = "{date}_diagnostics.txt",
    ) -> Path:
        run_date = run_date or date.today()
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = filename_format.format(date=run_date.isoformat())
        path = output_dir / filename
        path.write_text(self.render_text_report(run_date), encoding="utf-8")
        return path

    def save_records_csv(
        self,
        output_dir: Path,
        run_date: date | None = None,
        filename: str = "{date}_rejections_detail.csv",
    ) -> Path:
        """Save all individual rejection records as CSV for deep analysis."""
        run_date = run_date or date.today()
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / filename.format(date=run_date.isoformat())
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=["ticker", "stage", "reason_code", "reason_label",
                            "detail", "strategy", "snapshot_summary", "score"],
            )
            writer.writeheader()
            for r in self.records:
                row = asdict(r)
                row["reason_label"] = REASON_LABELS.get(r.reason_code, r.reason_code)
                writer.writerow(row)
        return path
