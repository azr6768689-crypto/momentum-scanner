"""
Pre-Breakout Compression strategy.

Finds stocks with compressed volatility near a clear resistance level.
These are coiling before a potential breakout — gives time to prepare.

Conditions:
- ATR(10) < 60% of ATR(50) (volatility compression)
- Price within 3% of 20d/50d/52w high resistance
- Uptrend: close > SMA50, SMA50 rising
- Breakout has NOT happened yet (today's high < resistance)

Output: always STATUS_WATCH with entry_trigger at resistance.
"""

from __future__ import annotations

import pandas as pd

from src.analytics.indicators import IndicatorSnapshot, atr
from src.strategies.base import (
    BaseStrategy, SetupSignal, SCANNER_PRE_BREAKOUT, STATUS_WATCH,
)


class PreBreakoutCompressionStrategy(BaseStrategy):
    name = "pre_breakout_compression"
    scanner_mode = SCANNER_PRE_BREAKOUT
    setup_type = "Pre-breakout compression"

    def detect(
        self,
        ticker: str,
        df: pd.DataFrame,
        snapshot: IndicatorSnapshot,
    ) -> SetupSignal | None:
        if not self.is_enabled():
            return None

        atr_short_p = int(self.p("atr_short_period", 10))
        atr_long_p  = int(self.p("atr_long_period", 50))
        atr_ratio_max = float(self.p("atr_ratio_max", 0.60))

        if len(df) < atr_long_p + 1:
            return None

        atr_short = atr(df, atr_short_p).iloc[-1]
        atr_long  = atr(df, atr_long_p).iloc[-1]
        if pd.isna(atr_short) or pd.isna(atr_long) or atr_long <= 0:
            return None

        atr_ratio = float(atr_short / atr_long)
        if atr_ratio > atr_ratio_max:
            return None

        # Find nearest unbroken resistance within max_pct
        max_pct = float(self.p("max_pct_below_resistance", 3.0))
        lookbacks = list(self.p("resistance_lookback_days", [20, 50, 252]))
        close = snapshot.close

        candidates: list[tuple[int, float]] = []
        for lb in lookbacks:
            if len(df) < lb:
                continue
            level = float(df["high"].iloc[-lb:].max())
            if level <= close:
                continue
            pct_below = (level / close - 1.0) * 100.0
            if pct_below <= max_pct:
                candidates.append((lb, level))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[1])
        chosen_lb, resistance = candidates[0]

        # Trend filter
        if snapshot.trend not in {"uptrend_strong", "uptrend_weak"}:
            return None

        # Not yet broken out
        if snapshot.high >= resistance:
            return None

        # Trade plan
        cons_window = min(10, len(df))
        cons_low  = float(df["low"].iloc[-cons_window:].min())
        cons_high = float(df["high"].iloc[-cons_window:].max())
        cons_range = cons_high - cons_low
        if cons_range <= 0:
            return None

        buffer = max(0.01, 0.0015 * resistance)
        entry = resistance + buffer
        stop = min(cons_low - 0.05 * cons_range, entry - 1.5 * snapshot.atr14)
        if stop >= entry:
            return None

        t1_mult = float(self.p("target_1_multiplier_of_range", 1.0))
        t2_mult = float(self.p("target_2_multiplier_of_range", 2.0))
        target_1 = resistance + t1_mult * cons_range
        target_2 = resistance + t2_mult * cons_range

        rr = SetupSignal.calc_risk_reward(entry, stop, target_1)
        if rr < 1.5:
            return None

        lb_name = {20: "20-day", 50: "50-day", 252: "52-week"}.get(chosen_lb, f"{chosen_lb}-day")
        pct_below_val = (resistance / close - 1.0) * 100.0

        reason = (
            f"Volatility compression (ATR{atr_short_p}/{atr_long_p}={atr_ratio:.2f}) "
            f"under {lb_name} resistance at ${resistance:.2f}. "
            f"Price ${close:.2f} is {pct_below_val:.1f}% below. "
            f"Consolidation range ${cons_range:.2f}."
        )
        invalidation = f"Close below ${cons_low:.2f} (consolidation low)."
        wait_for = f"Break and close above ${entry:.2f} on RVOL >= 1.5"

        base_q = int(self.p("base_setup_quality", 75))
        prox_bonus = max(0, int((1.0 - pct_below_val / max_pct) * 10))
        comp_bonus = int((atr_ratio_max - atr_ratio) * 25)

        warnings: list[str] = []
        if snapshot.dollar_volume_20 < 5_000_000:
            warnings.append(f"Low dollar volume (${snapshot.dollar_volume_20:,.0f})")

        return SetupSignal(
            ticker=ticker,
            setup_type=self.setup_type,
            strategy_module=self.name,
            scanner_mode=self.scanner_mode,
            status=STATUS_WATCH,
            entry_trigger=round(entry, 2),
            stop_loss=round(stop, 2),
            target_1=round(target_1, 2),
            target_2=round(target_2, 2),
            risk_reward=round(rr, 2),
            reason=reason,
            invalidation=invalidation,
            score_hint=base_q + prox_bonus + comp_bonus,
            warnings=warnings,
            wait_for=wait_for,
            factor_inputs={
                "atr_ratio": atr_ratio,
                "resistance_lookback": chosen_lb,
                "consolidation_range": cons_range,
                "pct_below_resistance": pct_below_val,
            },
            as_of=snapshot.as_of,
        )
