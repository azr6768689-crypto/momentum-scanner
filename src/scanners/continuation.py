"""
Continuation Scanner.

Finds stocks already in a strong move but still tradeable with enough upside.

Now logs every downgrade decision to diagnostics so the user can see
exactly why setups were demoted from Trigger to Wait/Ignore.
"""

from __future__ import annotations

from src.analytics.indicators import IndicatorSnapshot
from src.strategies.base import (
    SetupSignal, STATUS_TRIGGER, STATUS_WATCH, STATUS_WAIT, STATUS_IGNORE,
)
from src.scanners.base import BaseScanner
from src.diagnostics import (
    REASON_DOWNGRADED_TO_WAIT, REASON_DOWNGRADED_TO_IGNORE,
    REASON_EXHAUSTION_CANDLE, REASON_REMAINING_UPSIDE_LOW,
    REASON_DAY_GAIN_TOO_HIGH,
)


class ContinuationScanner(BaseScanner):
    mode = "continuation"

    def post_filter(
        self,
        signal: SetupSignal,
        snapshot: IndicatorSnapshot,
    ) -> SetupSignal | None:
        cont = self.settings.continuation
        ext = self.settings.extension
        th = self.settings.thresholds

        day_gain = snapshot.pct_change_1d

        # --- Reject: huge day move without clean pattern ---
        if day_gain > cont.day_gain_pct_absolute_max:
            fi = signal.factor_inputs
            has_clean_pattern = (
                fi.get("vol_declining_in_flag", False)
                or fi.get("reversal_candle", False)
            )
            if not has_clean_pattern:
                self._log(
                    signal.ticker, REASON_DAY_GAIN_TOO_HIGH,
                    f"day +{day_gain:.1f}% > {cont.day_gain_pct_absolute_max}% "
                    f"without clean continuation pattern",
                    strategy=signal.strategy_module, snap=snapshot,
                )
                return None

        # --- Volume gate for high-gain stocks ---
        vol_cfg = self.settings.volume
        if day_gain > 10.0 and snapshot.rvol_20 < vol_cfg.rvol_min_continuation_high_gain:
            signal.warnings.append(
                f"Stock up {day_gain:.1f}% but RVOL {snapshot.rvol_20:.1f}x "
                f"below {vol_cfg.rvol_min_continuation_high_gain:.1f}x required "
                f"for high-gain continuation"
            )
            signal.status = STATUS_WAIT
            self._log(
                signal.ticker, REASON_DOWNGRADED_TO_WAIT,
                f"high-gain day ({day_gain:.1f}%) but low RVOL ({snapshot.rvol_20:.1f}x) "
                f"— downgraded to Wait",
                strategy=signal.strategy_module, snap=snapshot,
            )

        # --- Extension check ---
        atr_ext = snapshot.atr_ext_above_sma20
        if atr_ext > th.max_atr_extension:
            fi = signal.factor_inputs
            has_flag = fi.get("flagpole_pct", 0) > 0
            has_reversal = fi.get("reversal_candle", False)

            if not has_flag and not has_reversal:
                signal.status = STATUS_WAIT
                signal.warnings.append(
                    f"Extended {atr_ext:.1f}x ATR above SMA20 — wait for pullback."
                )
                self._log(
                    signal.ticker, REASON_DOWNGRADED_TO_WAIT,
                    f"extended ({atr_ext:.1f}x) without flag/reversal — downgraded",
                    strategy=signal.strategy_module, snap=snapshot,
                )

        # --- Remaining upside check ---
        if signal.entry_trigger > 0 and signal.stop_loss > 0:
            upside = signal.target_1 - snapshot.close
            downside = snapshot.close - signal.stop_loss
            if downside > 0:
                remaining_rr = upside / downside
                if remaining_rr < 1.5:
                    signal.status = STATUS_IGNORE
                    signal.warnings.append(
                        f"Remaining R/R only {remaining_rr:.1f}:1 from current "
                        f"price — too late."
                    )
                    self._log(
                        signal.ticker, REASON_REMAINING_UPSIDE_LOW,
                        f"remaining R/R from current price {remaining_rr:.1f}:1 < 1.5",
                        strategy=signal.strategy_module, snap=snapshot,
                    )

        # --- Vertical / exhaustion candle ---
        if day_gain > 5.0:
            bar_range = snapshot.high - snapshot.low
            if bar_range > 0:
                close_pos = (snapshot.close - snapshot.low) / bar_range
                if close_pos < 0.3:
                    signal.status = STATUS_IGNORE
                    signal.warnings.append(
                        f"Close in bottom {close_pos*100:.0f}% of range "
                        f"on {day_gain:.1f}% day — possible exhaustion."
                    )
                    self._log(
                        signal.ticker, REASON_EXHAUSTION_CANDLE,
                        f"day +{day_gain:.1f}% but close in bottom "
                        f"{close_pos*100:.0f}% of range",
                        strategy=signal.strategy_module, snap=snapshot,
                    )

        return signal
