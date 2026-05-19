"""
Pre-Breakout Scanner.

Finds stocks coiling before a major breakout. Status is typically Watch.

Rejections logged to diagnostics.
"""

from __future__ import annotations

from src.analytics.indicators import IndicatorSnapshot
from src.strategies.base import SetupSignal, STATUS_WATCH
from src.scanners.base import BaseScanner
from src.diagnostics import (
    REASON_TREND_DOWNTREND, REASON_TREND_INSUFFICIENT, REASON_BELOW_SMA50,
)


class PreBreakoutScanner(BaseScanner):
    mode = "pre_breakout"

    def post_filter(
        self,
        signal: SetupSignal,
        snapshot: IndicatorSnapshot,
    ) -> SetupSignal | None:
        # Pre-breakout signals should always be Watch
        if signal.status != STATUS_WATCH:
            signal.status = STATUS_WATCH

        # Reject if stock is in a downtrend
        if snapshot.trend == "downtrend":
            self._log(
                signal.ticker, REASON_TREND_DOWNTREND,
                "pre-breakout compression in downtrend — likely failed breakout",
                strategy=signal.strategy_module, snap=snapshot,
            )
            return None
        if snapshot.trend == "insufficient_data":
            self._log(
                signal.ticker, REASON_TREND_INSUFFICIENT,
                "insufficient trend data",
                strategy=signal.strategy_module, snap=snapshot,
            )
            return None

        # Prefer close above SMA50
        if snapshot.close < snapshot.sma50:
            self._log(
                signal.ticker, REASON_BELOW_SMA50,
                f"close ${snapshot.close:.2f} below SMA50 ${snapshot.sma50:.2f}",
                strategy=signal.strategy_module, snap=snapshot,
            )
            return None

        return signal
