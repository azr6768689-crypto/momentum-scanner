"""
Liquidity scorer.

Takes LiquidityMetrics and produces a 0-100 liquidity score.
Each factor is scored 0-100 independently, then weighted and summed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from src.liquidity.metrics import LiquidityMetrics


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _linear(val: float, low: float, high: float) -> float:
    """Map val from [low, high] to [0, 100], clamped."""
    if high <= low:
        return 50.0
    return _clamp((val - low) / (high - low) * 100.0)


def _log_linear(val: float, low: float, high: float) -> float:
    """Log-scale mapping. Good for dollar volume where range is wide."""
    if val <= 0 or low <= 0:
        return 0.0
    log_val = math.log10(val)
    log_lo  = math.log10(low)
    log_hi  = math.log10(high)
    return _clamp((log_val - log_lo) / (log_hi - log_lo) * 100.0)


@dataclass(frozen=True)
class LiquidityScoreResult:
    """Scored liquidity assessment for one ticker."""
    ticker: str
    liquidity_score: int            # 0-100 final score
    factor_scores: dict[str, float]  # individual factor scores
    warnings: list[str]             # accumulated warnings from metrics + scorer
    passed: bool                    # True if score >= min_liquidity_score


def score_liquidity(
    metrics: LiquidityMetrics,
    cfg,  # LiquidityV2Config
) -> LiquidityScoreResult:
    """Compute the 0-100 liquidity score."""
    w = cfg.score_weights
    factors: dict[str, float] = {}

    # 1. Price quality: $10=40, $20=60, $50=80, $100+=100, <$5=0
    factors["price_quality"] = _linear(metrics.current_price, 5.0, 100.0)

    # 2. Average volume: 700K=50, 1M=70, 3M=90, 10M+=100
    factors["avg_volume"] = _log_linear(metrics.avg_volume_20d, 200_000, 10_000_000)

    # 3. Average dollar volume: $10M=50, $50M=75, $200M+=100
    factors["avg_dollar_volume"] = _log_linear(
        metrics.avg_dollar_volume_20d, 2_000_000, 500_000_000
    )

    # 4. Current volume (today's volume vs avg). Higher = more active today
    if metrics.avg_volume_20d > 0:
        vol_ratio = metrics.current_volume / metrics.avg_volume_20d
        factors["current_volume"] = _linear(vol_ratio, 0.2, 2.0)
    else:
        factors["current_volume"] = 0.0

    # 5. Current dollar volume: $1M=30, $10M=60, $100M+=100
    factors["current_dollar_volume"] = _log_linear(
        metrics.current_dollar_volume, 500_000, 200_000_000
    )

    # 6. Spread quality (neutral 50 if no data)
    if metrics.has_quote_data and metrics.spread_pct is not None:
        # Tighter is better: 0.02%=100, 0.30%=50, 0.50%=20, >1%=0
        factors["spread_quality"] = _clamp(100.0 - (metrics.spread_pct * 200.0))
    else:
        factors["spread_quality"] = 50.0  # neutral when unknown

    # 7. Exchange quality
    if metrics.is_acceptable_exchange:
        factors["exchange_quality"] = 100.0
    elif metrics.exchange == "UNKNOWN":
        factors["exchange_quality"] = 40.0  # penalty for unknown
    else:
        factors["exchange_quality"] = 0.0   # OTC/PINK would be rejected earlier

    # 8. Market cap quality (neutral 50 if unknown)
    if metrics.market_cap is not None:
        # $300M=30, $1B=60, $10B=80, $100B+=100
        factors["market_cap_quality"] = _log_linear(
            metrics.market_cap, 100_000_000, 200_000_000_000
        )
    else:
        factors["market_cap_quality"] = 50.0

    # 9. Missing data penalty
    missing_count = 0
    if not metrics.has_quote_data:
        missing_count += 1
    if metrics.market_cap is None:
        missing_count += 1
    if metrics.float_shares is None:
        missing_count += 1
    # Score: 100 = no missing, 0 = all 3 missing
    factors["missing_data_penalty"] = _clamp(100.0 - missing_count * 33.3)

    # Weighted sum
    total_weight = sum(w.values())
    if total_weight <= 0:
        total_weight = 100

    weighted = 0.0
    for name, factor_val in factors.items():
        weight = w.get(name, 0)
        weighted += factor_val * weight / total_weight

    final = int(round(_clamp(weighted)))

    # Build warnings from metrics + scorer additions
    all_warnings = list(metrics.warnings)
    if metrics.is_low_float:
        all_warnings.append("LOW FLOAT — expect higher volatility and wider spreads")
    if metrics.is_small_cap:
        all_warnings.append("SMALL CAP — institutional liquidity may be limited")
    if final < cfg.warn_liquidity_score:
        all_warnings.append(
            f"Liquidity score {final} is below warning threshold {cfg.warn_liquidity_score}"
        )

    return LiquidityScoreResult(
        ticker=metrics.ticker,
        liquidity_score=final,
        factor_scores=factors,
        warnings=all_warnings,
        passed=final >= cfg.min_liquidity_score,
    )
