"""
Bull Flag Continuation strategy.

Looks for:
1. A strong prior leg up (flagpole): >= 15% gain over last 15 bars
2. A tight pullback forming a flag: 3-10 bars, retraces <= 50% of pole
3. Volume declining during the flag (healthy consolidation)
4. Close still above SMA20 and SMA50

Trigger: break above the flag high.
Stop: below the flag low.
Targets: based on flagpole height projection.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.analytics.indicators import IndicatorSnapshot
from src.strategies.base import (
    BaseStrategy, SetupSignal, SCANNER_CONTINUATION,
    STATUS_TRIGGER, STATUS_WATCH,
)


class BullFlagContinuationStrategy(BaseStrategy):
    name = "bull_flag"
    scanner_mode = SCANNER_CONTINUATION
    setup_type = "Bull flag continuation"

    def detect(
        self,
        ticker: str,
        df: pd.DataFrame,
        snapshot: IndicatorSnapshot,
    ) -> SetupSignal | None:
        if not self.is_enabled():
            return None

        pole_min_pct = float(self.p("flagpole_min_pct", 15.0))
        pole_max_bars = int(self.p("flagpole_max_bars", 15))
        flag_min_bars = int(self.p("flag_min_bars", 3))
        flag_max_bars = int(self.p("flag_max_bars", 10))
        flag_max_retrace = float(self.p("flag_max_retrace_pct", 50.0))

        needed = pole_max_bars + flag_max_bars + 5
        if len(df) < needed:
            return None

        # Trend gate
        if snapshot.trend not in {"uptrend_strong", "uptrend_weak"}:
            return None

        # --- Search for a flagpole + flag pattern ---
        # We scan backward: the flag is at the end, the pole is before it.
        # Try different flag lengths to find the best pattern.

        best_signal: SetupSignal | None = None
        best_rr = 0.0

        for flag_bars in range(flag_min_bars, flag_max_bars + 1):
            # Flag = last `flag_bars` bars
            flag_slice = df.iloc[-(flag_bars):]
            flag_high = float(flag_slice["high"].max())
            flag_low  = float(flag_slice["low"].min())

            # Pole = bars before the flag, up to pole_max_bars
            pole_end_idx = len(df) - flag_bars
            pole_start_idx = max(0, pole_end_idx - pole_max_bars)
            pole_slice = df.iloc[pole_start_idx:pole_end_idx]

            if len(pole_slice) < 3:
                continue

            pole_low  = float(pole_slice["low"].min())
            pole_high = float(pole_slice["high"].max())

            if pole_low <= 0:
                continue

            pole_pct = (pole_high / pole_low - 1.0) * 100.0
            if pole_pct < pole_min_pct:
                continue  # pole isn't strong enough

            pole_height = pole_high - pole_low

            # Flag retracement check
            retrace = (pole_high - flag_low) / pole_height * 100.0 if pole_height > 0 else 100
            if retrace > flag_max_retrace:
                continue  # flag pulled back too much

            # Flag should have lower average volume than pole (healthy)
            pole_avg_vol = float(pole_slice["volume"].mean())
            flag_avg_vol = float(flag_slice["volume"].mean())
            vol_declining = flag_avg_vol < pole_avg_vol

            # Current close should be within the flag range
            close = snapshot.close
            if close < flag_low or close > flag_high * 1.02:
                continue  # closed outside flag

            # Trade plan
            buffer = max(0.01, 0.001 * flag_high)
            entry = flag_high + buffer

            stop = flag_low - 0.01 * flag_low
            if stop >= entry:
                continue

            t1_pct = float(self.p("target_1_pct_of_flagpole", 100)) / 100.0
            t2_pct = float(self.p("target_2_pct_of_flagpole", 150)) / 100.0
            target_1 = flag_high + t1_pct * pole_height
            target_2 = flag_high + t2_pct * pole_height

            rr = SetupSignal.calc_risk_reward(entry, stop, target_1)
            if rr < 1.5:
                continue

            # Is today breaking the flag?
            triggered = snapshot.high > flag_high and snapshot.rvol_20 >= 1.5

            if rr > best_rr:
                # Score hint
                base_q = int(self.p("base_setup_quality", 80))
                vol_bonus = 8 if vol_declining else 0
                pole_bonus = min(10, int((pole_pct - pole_min_pct) / 5))
                tight_bonus = max(0, int((flag_max_retrace - retrace) / 10))

                warnings: list[str] = []
                if not vol_declining:
                    warnings.append("Volume not declining during flag (less clean)")
                if snapshot.dist_from_sma20_pct > 10:
                    warnings.append(f"Extended {snapshot.dist_from_sma20_pct:.1f}% above SMA20")

                status = STATUS_TRIGGER if triggered else STATUS_WATCH

                reason = (
                    f"Bull flag: {pole_pct:.0f}% pole over {len(pole_slice)} bars, "
                    f"then {flag_bars}-bar flag retracing {retrace:.0f}% of pole. "
                    f"Flag range ${flag_low:.2f}-${flag_high:.2f}. "
                    f"{'Volume declining in flag.' if vol_declining else 'Volume elevated in flag.'}"
                )
                invalidation = f"Close below ${flag_low:.2f} (flag low)."
                wait_for = (
                    f"Hold above ${flag_high:.2f} through close."
                    if triggered else
                    f"Break above ${entry:.2f} on RVOL >= 1.5"
                )

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
                    score_hint=base_q + vol_bonus + pole_bonus + tight_bonus,
                    warnings=warnings,
                    wait_for=wait_for,
                    factor_inputs={
                        "flagpole_pct": pole_pct,
                        "flag_bars": flag_bars,
                        "retrace_pct": retrace,
                        "vol_declining_in_flag": vol_declining,
                        "pole_height": pole_height,
                    },
                    as_of=snapshot.as_of,
                )
                best_rr = rr

        return best_signal
