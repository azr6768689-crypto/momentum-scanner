"""
Scoring engine.

Takes a SetupSignal + IndicatorSnapshot and produces a final 0-100 score.

The score is a weighted sum of normalized factor scores. Weights come from
config/settings.yaml -> scoring.weights. Each factor is independently
scored 0-100, then combined.

This engine does NOT decide status — that's the scanner's job.
It only produces the numeric score that determines ranking.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.analytics.indicators import IndicatorSnapshot
from src.strategies.base import SetupSignal


@dataclass(frozen=True)
class ScoredSignal:
    """A signal with its final score attached."""
    signal: SetupSignal
    final_score: int          # 0-100
    factor_scores: dict[str, float]   # individual factor scores for transparency
    score_band: str           # "elite" | "very_strong" | "watch_only" | "excluded"


def _clamp(val: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, val))


def _linear_scale(val: float, low: float, high: float) -> float:
    """Map val from [low, high] to [0, 100]. Clamped."""
    if high <= low:
        return 50.0
    return _clamp((val - low) / (high - low) * 100.0)


class ScoreEngine:
    """Computes final 0-100 score for each signal."""

    def __init__(self, scoring_config: Any) -> None:
        self.weights: dict[str, int] = dict(scoring_config.weights)
        self.ext_penalty_max: int = scoring_config.extension_penalty_max
        self.threshold_include: int = scoring_config.threshold_include
        self.threshold_strong: int = scoring_config.threshold_strong
        self.threshold_elite: int = scoring_config.threshold_elite

        # Normalize weights to sum to 100 (if they don't already)
        total = sum(self.weights.values())
        if total > 0 and total != 100:
            factor = 100.0 / total
            self.weights = {k: v * factor for k, v in self.weights.items()}

    def score(
        self,
        signal: SetupSignal,
        snapshot: IndicatorSnapshot,
    ) -> ScoredSignal:
        """Compute the final score for one signal."""
        factors: dict[str, float] = {}

        # --- 1. Trend strength (0-100) ---
        trend_map = {
            "uptrend_strong": 100.0,
            "uptrend_weak": 60.0,
            "sideways": 30.0,
            "downtrend": 0.0,
            "insufficient_data": 10.0,
        }
        factors["trend_strength"] = trend_map.get(snapshot.trend, 30.0)

        # --- 2. Setup quality (from strategy's score_hint) ---
        factors["setup_quality"] = _clamp(float(signal.score_hint))

        # --- 3. Relative volume ---
        # Scale: 0.5x -> 0, 1.5x -> 50, 3.0x -> 100, cap at 5x
        factors["relative_volume"] = _linear_scale(snapshot.rvol_20, 0.5, 3.5)

        # --- 4. RS vs SPY (using dist_from_sma50 as proxy in Phase 1) ---
        # In Phase 1 without real RS, we use the strength of the stock's own
        # trend. With real data this will be replaced by actual RS percentile.
        factors["rs_vs_primary"] = _linear_scale(snapshot.dist_from_sma50_pct, -5.0, 15.0)

        # --- 5. RS vs QQQ (same proxy) ---
        factors["rs_vs_secondary"] = _linear_scale(snapshot.dist_from_sma20_pct, -3.0, 10.0)

        # --- 6. Sector strength (disabled Phase 1 — default 50) ---
        factors["sector_strength"] = 50.0

        # --- 7. Dollar volume / liquidity ---
        # Scale: $5M -> 0, $50M -> 70, $200M+ -> 100
        dv = snapshot.dollar_volume_20
        if dv <= 0:
            factors["dollar_volume"] = 0.0
        else:
            factors["dollar_volume"] = _linear_scale(dv / 1_000_000, 5.0, 200.0)

        # --- 8. Price action quality ---
        # Close in range (higher = bullish), plus lack of negative change
        bar_range = snapshot.high - snapshot.low
        if bar_range > 0:
            close_in_range = (snapshot.close - snapshot.low) / bar_range * 100.0
        else:
            close_in_range = 50.0
        # Bonus for positive day
        day_bonus = min(30.0, max(0.0, snapshot.pct_change_1d * 5.0))
        factors["price_action_quality"] = _clamp(close_in_range * 0.7 + day_bonus)

        # --- 9. Risk/reward ---
        # Scale: 1.5 -> 0, 2.0 -> 30, 3.0 -> 70, 4.0 -> 100
        factors["risk_reward"] = _linear_scale(signal.risk_reward, 1.5, 4.0)

        # --- 10. Remaining upside ---
        # How much room to target_1 vs how far the stop is
        if signal.entry_trigger > signal.stop_loss:
            upside_pct = (signal.target_1 / signal.entry_trigger - 1.0) * 100.0
            factors["remaining_upside"] = _linear_scale(upside_pct, 1.0, 10.0)
        else:
            factors["remaining_upside"] = 0.0

        # --- 11. Catalyst (disabled Phase 1) ---
        factors["catalyst"] = 50.0

        # --- 12. Spread quality (disabled Phase 1) ---
        factors["spread_quality"] = 50.0

        # --- Weighted sum ---
        weighted_sum = 0.0
        for factor_name, factor_score in factors.items():
            weight = self.weights.get(factor_name, 0)
            weighted_sum += factor_score * weight / 100.0

        # --- Extension penalty ---
        penalty = 0.0
        atr_ext = snapshot.atr_ext_above_sma20
        if atr_ext > 1.5:
            penalty = min(self.ext_penalty_max, (atr_ext - 1.5) * 3.0)

        final = int(round(_clamp(weighted_sum - penalty)))

        # --- Band ---
        if final >= self.threshold_elite:
            band = "elite"
        elif final >= self.threshold_strong:
            band = "very_strong"
        elif final >= self.threshold_include:
            band = "watch_only"
        else:
            band = "excluded"

        return ScoredSignal(
            signal=signal,
            final_score=final,
            factor_scores=factors,
            score_band=band,
        )

    def score_batch(
        self,
        signals: list[SetupSignal],
        snapshots: dict[str, IndicatorSnapshot],
    ) -> list[ScoredSignal]:
        """Score a list of signals. Returns scored list sorted by score descending."""
        scored: list[ScoredSignal] = []
        for sig in signals:
            snap = snapshots.get(sig.ticker)
            if snap is None:
                continue
            scored.append(self.score(sig, snap))

        scored.sort(key=lambda s: s.final_score, reverse=True)
        return scored
