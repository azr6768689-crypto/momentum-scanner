"""
Pullback After Momentum strategy.

Looks for:
1. A prior strong leg up: 10-25% advance over the prior ~10 bars
2. A controlled pullback of 2-5 bars toward SMA20/EMA21
3. Price still above SMA50 (uptrend intact)
4. The latest bar shows a bullish reversal candle (close > open, close
   near high) on the support bounce

Trigger: reversal candle on the pullback low.
Stop: below the pullback low or SMA50.
Targets: prior swing high and +1x the prior leg.
"""

from __future__ import annotations

import pandas as pd

from src.analytics.indicators import IndicatorSnapshot, sma
from src.strategies.base import (
    BaseStrategy, SetupSignal, SCANNER_CONTINUATION,
    STATUS_TRIGGER, STATUS_WATCH,
)


class PullbackAfterMomentumStrategy(BaseStrategy):
    name = "pullback_after_momentum"
    scanner_mode = SCANNER_CONTINUATION
    setup_type = "Pullback after momentum"

    def detect(
        self,
        ticker: str,
        df: pd.DataFrame,
        snapshot: IndicatorSnapshot,
    ) -> SetupSignal | None:
        if not self.is_enabled():
            return None

        prior_min = float(self.p("prior_leg_min_pct", 10.0))
        prior_max = float(self.p("prior_leg_max_pct", 25.0))
        prior_lb  = int(self.p("prior_leg_lookback_bars", 10))
        pb_min    = int(self.p("pullback_min_bars", 2))
        pb_max    = int(self.p("pullback_max_bars", 5))

        needed = prior_lb + pb_max + 5
        if len(df) < needed:
            return None

        # Trend gate
        if snapshot.trend in {"downtrend", "insufficient_data"}:
            return None
        if snapshot.close < snapshot.sma50:
            return None

        # --- Search for prior leg + pullback ---
        # We try different pullback lengths to find the best match.

        best_signal: SetupSignal | None = None
        best_score = 0

        for pb_bars in range(pb_min, pb_max + 1):
            # Pullback = last pb_bars bars
            pb_slice = df.iloc[-pb_bars:]
            pb_low = float(pb_slice["low"].min())

            # Prior leg = bars before pullback, length prior_lb
            leg_end = len(df) - pb_bars
            leg_start = max(0, leg_end - prior_lb)
            leg_slice = df.iloc[leg_start:leg_end]

            if len(leg_slice) < 3:
                continue

            leg_low  = float(leg_slice["low"].min())
            leg_high = float(leg_slice["high"].max())

            if leg_low <= 0:
                continue

            leg_pct = (leg_high / leg_low - 1.0) * 100.0
            if leg_pct < prior_min or leg_pct > prior_max:
                continue

            # Pullback should touch or approach SMA20
            sma20_val = snapshot.sma20
            dist_to_sma20 = abs(pb_low - sma20_val) / sma20_val * 100.0
            # Must be within 3% of SMA20 (touching or slightly above/below)
            if dist_to_sma20 > 3.0:
                continue

            # Reversal candle check: last bar should be bullish
            last = df.iloc[-1]
            is_bullish = last["close"] > last["open"]
            last_range = last["high"] - last["low"]
            close_in_range = ((last["close"] - last["low"]) / last_range * 100.0) if last_range > 0 else 50
            require_reversal = bool(self.p("require_bullish_reversal_candle", True))

            if require_reversal and (not is_bullish or close_in_range < 60):
                continue

            # Trade plan
            close = snapshot.close
            entry = round(close, 2)  # entry at current level on reversal

            # Stop below pullback low or SMA50
            stop_pb = pb_low - 0.015 * pb_low
            stop_sma50 = snapshot.sma50 - 0.01 * snapshot.sma50
            stop = max(stop_pb, stop_sma50)  # use the higher (tighter) of the two
            if stop >= entry:
                stop = entry - snapshot.atr14
            if stop >= entry:
                continue

            # Target 1: prior swing high
            target_1 = leg_high
            # Target 2: entry + 1x the prior leg height
            leg_height = leg_high - leg_low
            target_2 = entry + leg_height

            if target_1 <= entry:
                target_1 = entry + snapshot.atr14
            if target_2 < target_1:
                target_2 = target_1

            rr = SetupSignal.calc_risk_reward(entry, stop, target_1)
            if rr < 1.5:
                continue

            # Score hint
            base_q = int(self.p("base_setup_quality", 78))
            reversal_bonus = 8 if is_bullish and close_in_range > 70 else 0
            proximity_bonus = max(0, int((3.0 - dist_to_sma20) * 4))
            leg_bonus = min(8, int((leg_pct - prior_min) / 3))
            score = base_q + reversal_bonus + proximity_bonus + leg_bonus

            if score > best_score:
                warnings: list[str] = []
                if snapshot.rvol_20 < 1.0:
                    warnings.append(f"Low RVOL ({snapshot.rvol_20:.1f}x) on bounce")
                if not is_bullish:
                    warnings.append("Last bar is not bullish (waiting for reversal)")

                triggered = is_bullish and close_in_range >= 60 and close > sma20_val
                status = STATUS_TRIGGER if triggered else STATUS_WATCH

                reason = (
                    f"Prior leg +{leg_pct:.0f}% over {len(leg_slice)} bars, "
                    f"then {pb_bars}-bar pullback to SMA20 (${sma20_val:.2f}). "
                    f"Pullback low ${pb_low:.2f} is {dist_to_sma20:.1f}% from SMA20. "
                    f"{'Bullish reversal candle on bounce.' if triggered else 'Waiting for reversal candle.'}"
                )
                invalidation = f"Close below ${stop:.2f} (pullback low / SMA50 zone)."
                if triggered:
                    wait_for = f"Hold above SMA20 (${sma20_val:.2f}) through close."
                else:
                    wait_for = f"Bullish reversal candle closing above SMA20 (${sma20_val:.2f})."

                best_signal = SetupSignal(
                    ticker=ticker,
                    setup_type=self.setup_type,
                    strategy_module=self.name,
                    scanner_mode=self.scanner_mode,
                    status=status,
                    entry_trigger=round(entry, 2),
                    stop_loss=round(stop, 2),
                    target_1=round(target_1, 2),
                    target_2=round(target_2, 2),
                    risk_reward=round(rr, 2),
                    reason=reason,
                    invalidation=invalidation,
                    score_hint=score,
                    warnings=warnings,
                    wait_for=wait_for,
                    factor_inputs={
                        "prior_leg_pct": leg_pct,
                        "pullback_bars": pb_bars,
                        "dist_to_sma20_pct": dist_to_sma20,
                        "reversal_candle": is_bullish and close_in_range >= 60,
                    },
                    as_of=snapshot.as_of,
                )
                best_score = score

        return best_signal
