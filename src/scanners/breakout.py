"""
Breakout Scanner.

Finds stocks breaking above 20d/50d/52w highs with volume confirmation.
Status: Trigger if confirmed, Watch if approaching.

Rejections + downgrades are logged to diagnostics.
"""

from __future__ import annotations

from src.analytics.indicators import IndicatorSnapshot
from src.strategies.base import (
    SetupSignal, STATUS_TRIGGER, STATUS_WATCH, STATUS_IGNORE,
)
from src.scanners.base import BaseScanner
from src.diagnostics import (
    REASON_TREND_DOWNTREND, REASON_TREND_INSUFFICIENT,
    REASON_LOW_RVOL, REASON_DOWNGRADED_TO_WAIT,
)


class BreakoutScanner(BaseScanner):
    mode = "breakout"

    def post_filter(
        self,
        signal: SetupSignal,
        snapshot: IndicatorSnapshot,
    ) -> SetupSignal | None:
        # Trend gate: breakouts in downtrend are fake breakouts more often
        if snapshot.trend == "downtrend":
            self._log(
                signal.ticker, REASON_TREND_DOWNTREND,
                "breakout signal but stock in downtrend",
                strategy=signal.strategy_module, snap=snapshot,
            )
            return None
        if snapshot.trend == "insufficient_data":
            self._log(
                signal.ticker, REASON_TREND_INSUFFICIENT,
                "insufficient bars to determine trend",
                strategy=signal.strategy_module, snap=snapshot,
            )
            return None

        # Volume gate for Trigger status
        fi = signal.factor_inputs
        rvol = fi.get("rvol", snapshot.rvol_20)
        min_rvol = self.settings.volume.rvol_min_breakout

        if signal.status == STATUS_TRIGGER and rvol < min_rvol:
            signal.status = STATUS_WATCH
            signal.warnings.append(
                f"RVOL {rvol:.1f}x below required {min_rvol:.1f}x "
                f"for confirmed breakout"
            )
            self._log(
                signal.ticker, REASON_LOW_RVOL,
                f"breakout confirmed but RVOL {rvol:.1f}x < {min_rvol:.1f}x "
                f"— downgraded to Watch",
                strategy=signal.strategy_module, snap=snapshot,
            )

        # If close is below the breakout level, this is pending or failed
        prior_high = fi.get("prior_high", 0)
        if prior_high > 0 and snapshot.close < prior_high:
            pct_from = (snapshot.close / prior_high - 1.0) * 100.0
            if pct_from < -2.0:
                # Too far below — no signal
                return None
            signal.status = STATUS_WATCH

        return signal
