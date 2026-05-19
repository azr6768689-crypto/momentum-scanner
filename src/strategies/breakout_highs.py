"""
Breakout Highs strategy (handles 20-day, 50-day, 52-week breakouts).

Consolidates three breakout variants into one module with a lookback param.
Each variant can be independently enabled via config/strategies.yaml.

Conditions:
- Today's high exceeds the prior-N-bar high (a genuine new-high breakout)
- Close in top 25% of today's range (strong close)
- Relative volume >= min threshold (confirms real interest)
- Not too extended (close < 1.5*ATR above breakout level)
- Uptrend: close > SMA20 and SMA50

Output: STATUS_TRIGGER if confirmed today, STATUS_WATCH if pending.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.analytics.indicators import IndicatorSnapshot, prior_rolling_high
from src.strategies.base import (
    BaseStrategy, SetupSignal, SCANNER_BREAKOUT,
    STATUS_TRIGGER, STATUS_WATCH,
)


class BreakoutHighsStrategy(BaseStrategy):
    """Generic breakout-above-N-day-high strategy.

    Instantiated three times with different params for 20d / 50d / 52w.
    """

    scanner_mode = SCANNER_BREAKOUT

    def __init__(
        self,
        params: dict[str, Any] | None = None,
        *,
        variant_name: str = "breakout_20d",
        variant_setup_type: str = "20-day high breakout",
        lookback: int = 20,
    ) -> None:
        super().__init__(params)
        self.name = variant_name
        self.setup_type = variant_setup_type
        self._lookback = lookback

    def detect(
        self,
        ticker: str,
        df: pd.DataFrame,
        snapshot: IndicatorSnapshot,
    ) -> SetupSignal | None:
        if not self.is_enabled():
            return None

        lookback = int(self.p("lookback_days", self._lookback))
        if len(df) < lookback + 1:
            return None

        # Prior N-bar high (excludes today)
        prior_h = prior_rolling_high(df, lookback)
        prior_level = float(prior_h.iloc[-1])
        if pd.isna(prior_level) or prior_level <= 0:
            return None

        close = snapshot.close
        high_today = snapshot.high
        low_today  = snapshot.low
        open_today = snapshot.open

        # --- Check breakout: today's high exceeds prior level ---
        breakout_happened = high_today > prior_level
        # "Confirmed" means the close is also above the level AND strong close
        today_range = high_today - low_today
        close_in_range = ((close - low_today) / today_range * 100.0) if today_range > 0 else 50.0
        require_top_quartile = bool(self.p("require_close_top_quartile", True))

        confirmed = (
            breakout_happened
            and close > prior_level
            and (not require_top_quartile or close_in_range >= 75.0)
        )

        # If breakout didn't happen and close is below — no signal at all
        # unless close is within 1% of level (pending breakout = Watch)
        pct_from_level = (close / prior_level - 1.0) * 100.0
        if not breakout_happened and pct_from_level < -1.0:
            return None

        # --- Volume confirmation ---
        min_rvol = float(self.p("min_rvol", 1.5))
        rvol = snapshot.rvol_20
        volume_ok = rvol >= min_rvol

        # --- Extension filter ---
        max_ext_atr = float(self.p("max_extension_atr", 1.5))
        extension = (close - prior_level) / snapshot.atr14 if snapshot.atr14 > 0 else 0
        too_extended = extension > max_ext_atr and confirmed

        # --- Trend filter ---
        if snapshot.trend in {"downtrend", "insufficient_data"}:
            return None

        # --- Determine status ---
        if confirmed and volume_ok and not too_extended:
            status = STATUS_TRIGGER
        else:
            status = STATUS_WATCH

        # --- Trade plan ---
        # Entry: at the breakout level (for Watch) or at close (for Trigger)
        if status == STATUS_TRIGGER:
            entry = round(close, 2)
        else:
            buffer = max(0.01, 0.001 * prior_level)
            entry = round(prior_level + buffer, 2)

        # Stop: below breakout level or below today's low, ATR-based floor
        stop_atr_mult = float(self.p("stop_atr_multiplier", 1.0))
        stop_structural = prior_level - 0.02 * prior_level  # 2% below level
        stop_atr = entry - stop_atr_mult * snapshot.atr14
        stop_today_low = low_today - 0.01 * low_today
        stop = max(stop_structural, stop_atr, stop_today_low)
        # Ensure stop is always below entry
        if stop >= entry:
            stop = entry - snapshot.atr14
        if stop >= entry:
            return None

        # Targets
        t1_mult = float(self.p("target_1_atr_multiplier", 2.0))
        t2_mult = float(self.p("target_2_atr_multiplier", 4.0))
        target_1 = entry + t1_mult * snapshot.atr14
        target_2 = entry + t2_mult * snapshot.atr14

        rr = SetupSignal.calc_risk_reward(entry, stop, target_1)
        if rr < 1.5:
            return None

        # --- Score hint ---
        base_q = int(self.p("base_setup_quality", 70))
        vol_bonus = min(15, int((rvol - 1.0) * 8)) if rvol > 1.0 else 0
        close_bonus = int(close_in_range / 20) if close_in_range > 50 else 0
        score_hint = base_q + vol_bonus + close_bonus

        # --- Narrative ---
        warnings: list[str] = []
        if not volume_ok:
            warnings.append(f"RVOL {rvol:.1f}x is below required {min_rvol:.1f}x")
        if too_extended:
            warnings.append(f"Extended {extension:.1f} ATRs above breakout level")

        lb_label = {20: "20-day", 50: "50-day", 252: "52-week"}.get(lookback, f"{lookback}-day")

        if confirmed:
            reason = (
                f"{lb_label} high breakout confirmed. Close ${close:.2f} above "
                f"${prior_level:.2f} with RVOL {rvol:.1f}x. "
                f"Close in top {close_in_range:.0f}% of range."
            )
        else:
            reason = (
                f"Approaching {lb_label} high at ${prior_level:.2f}. "
                f"Close ${close:.2f} is {pct_from_level:+.1f}% from level. "
                f"RVOL {rvol:.1f}x."
            )

        invalidation = f"Close back below ${prior_level:.2f} ({lb_label} high level)."
        if confirmed:
            wait_for = f"Hold above ${prior_level:.2f} through close."
        else:
            wait_for = f"Break and hold above ${entry:.2f} on RVOL >= {min_rvol:.1f}x."

        return SetupSignal(
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
            score_hint=score_hint,
            warnings=warnings,
            wait_for=wait_for,
            factor_inputs={
                "lookback": lookback,
                "prior_high": prior_level,
                "breakout_happened": breakout_happened,
                "close_in_range_pct": close_in_range,
                "rvol": rvol,
                "extension_atr": extension,
            },
            as_of=snapshot.as_of,
        )


# --- Factory functions for the three variants ------------------------------

def create_breakout_20d(params: dict[str, Any]) -> BreakoutHighsStrategy:
    return BreakoutHighsStrategy(
        params, variant_name="breakout_20d",
        variant_setup_type="20-day high breakout", lookback=20,
    )

def create_breakout_50d(params: dict[str, Any]) -> BreakoutHighsStrategy:
    return BreakoutHighsStrategy(
        params, variant_name="breakout_50d",
        variant_setup_type="50-day high breakout", lookback=50,
    )

def create_breakout_52w(params: dict[str, Any]) -> BreakoutHighsStrategy:
    return BreakoutHighsStrategy(
        params, variant_name="breakout_52w",
        variant_setup_type="52-week high breakout", lookback=252,
    )
