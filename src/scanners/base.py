"""
Base scanner.

A scanner does three things:
1. Receives a list of strategy modules assigned to it.
2. For each ticker, runs every assigned strategy.
3. Applies quality gates (liquidity, R/R, extension) and may override status.

CHANGE in Group F: every rejection is now logged to a DiagnosticsCollector
(if one is provided). The behavior is identical — the collector is optional
and read-only. Without it, scanner runs exactly as before.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import pandas as pd

from src.analytics.indicators import IndicatorSnapshot, compute_snapshot
from src.strategies.base import (
    BaseStrategy, SetupSignal,
    STATUS_WATCH, STATUS_TRIGGER, STATUS_WAIT, STATUS_IGNORE, STATUS_INVALIDATED,
)
from src.diagnostics import (
    DiagnosticsCollector,
    REASON_LIQUIDITY_PRICE, REASON_LIQUIDITY_VOLUME, REASON_LIQUIDITY_DOLLAR,
    REASON_INSUFFICIENT_BARS, REASON_NO_PATTERN,
    REASON_LOW_RR, REASON_EXTENDED_ATR, REASON_DAY_GAIN_TOO_HIGH,
    REASON_DOWNGRADED_TO_WAIT,
)

log = logging.getLogger(__name__)


def _snap_summary(snap: IndicatorSnapshot) -> str:
    """One-line summary of a snapshot for diagnostics."""
    return (
        f"close=${snap.close:.2f} rvol={snap.rvol_20:.1f}x "
        f"dist_s20={snap.dist_from_sma20_pct:+.1f}% atr_ext={snap.atr_ext_above_sma20:.1f}x "
        f"trend={snap.trend}"
    )


class BaseScanner:
    """Abstract scanner. Subclasses override post_filter() if needed."""

    mode: str = "abstract"

    def __init__(
        self,
        strategies: list[BaseStrategy],
        settings: Any,
        diagnostics: DiagnosticsCollector | None = None,
    ) -> None:
        # Only keep strategies assigned to this scanner mode
        self.strategies = [s for s in strategies if s.scanner_mode == self.mode]
        self.settings = settings
        self.diag = diagnostics  # may be None — that's fine

    def _log(self, ticker: str, reason: str, detail: str, strategy: str = "",
             snap: IndicatorSnapshot | None = None) -> None:
        """Helper to log a rejection to diagnostics (if available)."""
        if self.diag is None:
            return
        self.diag.record(
            ticker=ticker,
            reason_code=reason,
            detail=detail,
            strategy=strategy,
            snapshot_summary=_snap_summary(snap) if snap else "",
        )

    def scan_ticker(
        self,
        ticker: str,
        df: pd.DataFrame,
        snapshot: IndicatorSnapshot | None = None,
    ) -> list[SetupSignal]:
        """Run all assigned strategies on one ticker. Return valid signals.

        If `snapshot` is provided, reuses it (much faster). Otherwise
        computes it from `df`.
        """
        if snapshot is None:
            snapshot = compute_snapshot(df)
        if snapshot is None:
            self._log(ticker, REASON_INSUFFICIENT_BARS,
                      f"only {len(df)} bars, need 50+")
            return []

        # --- Gate 1: liquidity ---
        liq = self.settings.liquidity
        if snapshot.close < liq.min_price:
            self._log(ticker, REASON_LIQUIDITY_PRICE,
                      f"price ${snapshot.close:.2f} < ${liq.min_price}",
                      snap=snapshot)
            return []
        if snapshot.avg_volume_20 < liq.min_avg_volume_20d:
            self._log(ticker, REASON_LIQUIDITY_VOLUME,
                      f"avg vol {snapshot.avg_volume_20:,.0f} < {liq.min_avg_volume_20d:,.0f}",
                      snap=snapshot)
            return []
        if snapshot.dollar_volume_20 < liq.min_avg_dollar_volume_20d:
            self._log(ticker, REASON_LIQUIDITY_DOLLAR,
                      f"$ vol ${snapshot.dollar_volume_20:,.0f} < ${liq.min_avg_dollar_volume_20d:,.0f}",
                      snap=snapshot)
            return []

        # --- Run each strategy ---
        signals: list[SetupSignal] = []
        for strategy in self.strategies:
            try:
                sig = strategy.detect(ticker, df, snapshot)
            except Exception as exc:
                log.warning("Strategy %s raised on %s: %s",
                            strategy.name, ticker, exc)
                continue

            if sig is None:
                self._log(ticker, REASON_NO_PATTERN,
                          f"strategy {strategy.name} did not match",
                          strategy=strategy.name, snap=snapshot)
                continue

            # --- Gate 2: R/R hard floor ---
            rr_min = self.settings.thresholds.min_risk_reward
            if sig.risk_reward < rr_min:
                self._log(ticker, REASON_LOW_RR,
                          f"R/R {sig.risk_reward:.1f} < {rr_min:.1f}",
                          strategy=strategy.name, snap=snapshot)
                continue

            # --- Gate 3: extension override ---
            sig = self._apply_extension_checks(sig, snapshot, strategy.name)
            if sig is None:
                continue

            # --- Scanner-specific post-filter ---
            sig = self.post_filter(sig, snapshot)
            if sig is None:
                # post_filter has its own logging via _post_log
                continue

            signals.append(sig)

        return signals

    def scan_universe(
        self,
        universe: dict[str, pd.DataFrame],
        snapshots: dict[str, IndicatorSnapshot] | None = None,
        progress_callback=None,
    ) -> list[SetupSignal]:
        """Run on a dict of {ticker: ohlcv_df}. Return all valid signals.

        If `snapshots` is provided, reuses precomputed snapshots (much faster).
        If `progress_callback(idx, total, ticker)` is provided, it's called
        every iteration.

        Uses thread-parallelism when the universe is large enough to benefit.
        """
        total = len(universe)
        try:
            workers = max(1, int(os.getenv("SCAN_SCANNER_WORKERS", "4")))
        except ValueError:
            workers = 4
        workers = min(workers, 8)

        if total < 100 or workers <= 1:
            all_signals: list[SetupSignal] = []
            for i, (ticker, df) in enumerate(universe.items(), start=1):
                snap = snapshots.get(ticker) if snapshots else None
                sigs = self.scan_ticker(ticker, df, snapshot=snap)
                all_signals.extend(sigs)
                if progress_callback is not None:
                    progress_callback(i, total, ticker)
            return all_signals

        all_signals = []
        items = list(universe.items())

        def _scan_one(ticker_df: tuple[str, pd.DataFrame]) -> tuple[str, list[SetupSignal]]:
            ticker, df = ticker_df
            snap = snapshots.get(ticker) if snapshots else None
            return ticker, self.scan_ticker(ticker, df, snapshot=snap)

        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_scan_one, item): item[0] for item in items}
            for future in as_completed(futures):
                ticker, sigs = future.result()
                all_signals.extend(sigs)
                done += 1
                if progress_callback is not None:
                    progress_callback(done, total, ticker)
        return all_signals

    # --- Override point for subclasses ---
    def post_filter(
        self,
        signal: SetupSignal,
        snapshot: IndicatorSnapshot,
    ) -> SetupSignal | None:
        """Scanner-mode-specific filtering. Default: pass through."""
        return signal

    # --- Internal helpers ---
    def _apply_extension_checks(
        self,
        sig: SetupSignal,
        snapshot: IndicatorSnapshot,
        strategy_name: str,
    ) -> SetupSignal | None:
        """Downgrade or reject extended setups."""
        th = self.settings.thresholds

        # Check ATR extension above SMA20
        atr_ext = snapshot.atr_ext_above_sma20
        if atr_ext > th.max_atr_extension:
            # In non-continuation scanners, downgrade to Wait
            if sig.scanner_mode != "continuation":
                sig.status = STATUS_WAIT
                sig.warnings.append(
                    f"Extended {atr_ext:.1f}x ATR above SMA20 (max {th.max_atr_extension}x)"
                )
                self._log(
                    sig.ticker, REASON_DOWNGRADED_TO_WAIT,
                    f"ext {atr_ext:.1f}x > {th.max_atr_extension}x — downgraded",
                    strategy=strategy_name, snap=snapshot,
                )

        # Hard reject on day gain without setup
        day_gain = snapshot.pct_change_1d
        ext_cfg = self.settings.extension
        if day_gain > ext_cfg.max_day_gain_pct_no_setup and sig.status != STATUS_TRIGGER:
            self._log(
                sig.ticker, REASON_DAY_GAIN_TOO_HIGH,
                f"day +{day_gain:.1f}% > {ext_cfg.max_day_gain_pct_no_setup}% and no Trigger",
                strategy=strategy_name, snap=snapshot,
            )
            return None

        return sig
