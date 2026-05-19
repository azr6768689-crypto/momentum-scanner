"""
Liquidity and tradability layer.

Runs BEFORE the momentum scanners. Only stocks that pass through here
will be evaluated by strategies.

Public API:
    run_liquidity_filter(tickers, universe, snapshots, provider, settings, diag)
        -> dict[str, LiquidityScoreResult]   (only tickers that PASSED)
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from src.data.base import DataProvider, SymbolMetadata, Quote
from src.analytics.indicators import IndicatorSnapshot
from src.diagnostics import DiagnosticsCollector

from .filters import apply_hard_gates, FilterResult
from .metrics import compute_liquidity_metrics, LiquidityMetrics
from .scorer import score_liquidity, LiquidityScoreResult


log = logging.getLogger(__name__)


def run_liquidity_filter(
    tickers: list[str],
    universe: dict[str, pd.DataFrame],
    snapshots: dict[str, IndicatorSnapshot],
    provider: DataProvider,
    settings: Any,       # Settings object
    diag: DiagnosticsCollector | None = None,
    metadata_by_ticker: dict[str, SymbolMetadata] | None = None,
) -> dict[str, LiquidityScoreResult]:
    """Run the full liquidity pipeline.

    1. For each ticker, fetch metadata + optional quote.
    2. Apply hard gates (exchange, asset type, price, volume, spread).
    3. For survivors, compute liquidity metrics and score.
    4. Drop tickers below min_liquidity_score.

    Returns:
        dict of {ticker: LiquidityScoreResult} for tickers that PASSED.
        Rejected tickers are logged to diagnostics.
    """
    cfg = settings.liquidity_v2
    metadata_by_ticker = metadata_by_ticker or {}
    passed: dict[str, LiquidityScoreResult] = {}

    for ticker in tickers:
        # Get snapshot (may not exist if insufficient bars)
        snapshot = snapshots.get(ticker)

        # Prefer universe-builder metadata when available. It already applied
        # the ETF/exchange classification used to build the scan universe and
        # avoids hundreds of provider metadata calls on large daily runs.
        metadata = metadata_by_ticker.get(ticker)
        if metadata is None:
            try:
                metadata = provider.get_metadata(ticker)
            except Exception:
                metadata = SymbolMetadata(symbol=ticker)

        # Get quote (may be None — that's fine)
        try:
            quote = provider.get_quote(ticker)
        except Exception:
            quote = None

        # Hard gates
        gate = apply_hard_gates(
            ticker=ticker,
            snapshot=snapshot,
            metadata=metadata,
            quote=quote,
            cfg=cfg,
            diag=diag,
        )
        if not gate.passed:
            continue

        # At this point snapshot is guaranteed non-None (hard_gates checks)
        assert snapshot is not None

        # Compute metrics
        metrics = compute_liquidity_metrics(
            ticker=ticker,
            snapshot=snapshot,
            metadata=metadata,
            quote=quote,
            cfg=cfg,
        )

        # Score
        result = score_liquidity(metrics, cfg)

        if not result.passed:
            if diag:
                diag.record(
                    ticker=ticker,
                    reason_code="liquidity_score_below_min",
                    detail=f"score {result.liquidity_score} < {cfg.min_liquidity_score}",
                    snapshot_summary=(
                        f"close=${snapshot.close:.2f} "
                        f"avgvol={snapshot.avg_volume_20:,.0f} "
                        f"dvol=${snapshot.dollar_volume_20:,.0f} "
                        f"liq_score={result.liquidity_score}"
                    ),
                )
            continue

        passed[ticker] = result

    log.info(
        "Liquidity filter: %d tickers in → %d passed (%d rejected)",
        len(tickers), len(passed), len(tickers) - len(passed),
    )

    return passed


__all__ = [
    "run_liquidity_filter",
    "LiquidityScoreResult",
    "LiquidityMetrics",
    "FilterResult",
]
