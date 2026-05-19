"""
Liquidity metrics.

Computes all measurable liquidity indicators for one ticker.
These are consumed by the scorer and by the CSV report.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.data.base import SymbolMetadata, Quote
from src.analytics.indicators import IndicatorSnapshot


@dataclass
class LiquidityMetrics:
    """Every liquidity data-point for one ticker. Used for scoring + reporting."""

    ticker: str

    # Price
    current_price: float

    # Volume
    avg_volume_20d: float
    current_volume: float
    relative_volume: float

    # Dollar volume
    avg_dollar_volume_20d: float
    current_dollar_volume: float

    # Spread
    spread_pct: float | None       # None if no quote data
    has_quote_data: bool

    # Exchange / asset type
    exchange: str
    asset_type: str
    is_acceptable_exchange: bool

    # Float / market cap
    market_cap: float | None       # None if unknown
    float_shares: float | None
    shares_outstanding: float | None

    # Flags
    is_low_float: bool
    is_small_cap: bool

    # Warnings (human-readable list)
    warnings: list[str]


def compute_liquidity_metrics(
    ticker: str,
    snapshot: IndicatorSnapshot,
    metadata: SymbolMetadata,
    quote: Quote | None,
    cfg,  # LiquidityV2Config
) -> LiquidityMetrics:
    """Compute all liquidity metrics for one ticker."""
    from src.data.base import ACCEPTABLE_EXCHANGES

    current_dvol = snapshot.close * snapshot.volume
    warnings: list[str] = []

    # Spread
    spread_pct: float | None = None
    if quote is not None:
        spread_pct = quote.spread_pct
        if spread_pct > cfg.warn_spread_pct:
            warnings.append(
                f"Wide spread: {spread_pct:.3f}% (warn threshold: {cfg.warn_spread_pct}%)"
            )

    # Market cap / float flags
    is_small_cap = False
    is_low_float = False

    if metadata.market_cap is not None:
        if metadata.market_cap < cfg.min_market_cap:
            warnings.append(
                f"Market cap ${metadata.market_cap / 1e6:.0f}M below "
                f"${cfg.min_market_cap / 1e6:.0f}M minimum"
            )
            is_small_cap = True
        elif metadata.market_cap < cfg.warn_market_cap:
            warnings.append(
                f"Small-cap: ${metadata.market_cap / 1e6:.0f}M "
                f"(preferred > ${cfg.warn_market_cap / 1e6:.0f}M)"
            )
            is_small_cap = True

    if metadata.float_shares is not None:
        if metadata.float_shares < cfg.low_float_threshold:
            warnings.append(
                f"Low float: {metadata.float_shares / 1e6:.1f}M shares "
                f"(< {cfg.low_float_threshold / 1e6:.0f}M) — higher volatility risk"
            )
            is_low_float = True

    # Volume quality
    if snapshot.avg_volume_20 < cfg.preferred_avg_volume:
        warnings.append(
            f"Avg volume {snapshot.avg_volume_20:,.0f} below preferred "
            f"{cfg.preferred_avg_volume:,.0f}"
        )
    if snapshot.dollar_volume_20 < cfg.preferred_avg_dollar_volume:
        warnings.append(
            f"Avg dollar volume ${snapshot.dollar_volume_20:,.0f} below preferred "
            f"${cfg.preferred_avg_dollar_volume:,.0f}"
        )

    # Exchange quality
    is_acceptable = metadata.exchange in ACCEPTABLE_EXCHANGES
    if not is_acceptable and metadata.exchange != "UNKNOWN":
        warnings.append(f"Non-standard exchange: {metadata.exchange}")

    return LiquidityMetrics(
        ticker=ticker,
        current_price=snapshot.close,
        avg_volume_20d=snapshot.avg_volume_20,
        current_volume=snapshot.volume,
        relative_volume=snapshot.rvol_20,
        avg_dollar_volume_20d=snapshot.dollar_volume_20,
        current_dollar_volume=current_dvol,
        spread_pct=spread_pct,
        has_quote_data=quote is not None,
        exchange=metadata.exchange,
        asset_type=metadata.asset_type,
        is_acceptable_exchange=is_acceptable,
        market_cap=metadata.market_cap,
        float_shares=metadata.float_shares,
        shares_outstanding=metadata.shares_outstanding,
        is_low_float=is_low_float,
        is_small_cap=is_small_cap,
        warnings=warnings,
    )
