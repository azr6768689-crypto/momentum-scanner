"""
Hard-gate liquidity filters.

These run first and produce binary PASS/REJECT decisions.
No scoring — just ruthless exclusion of untradable symbols.

Order:
1. Asset type (no warrants, rights, units, preferred, test)
2. Exchange (no OTC, pink sheets)
3. Active status (no delisted/inactive)
4. Price floor
5. Average volume floor
6. Average dollar volume floor
7. Spread (if data available and apply_spread_filter=True)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.data.base import (
    SymbolMetadata, Quote,
    TRADABLE_ASSET_TYPES, EXCLUDED_ASSET_TYPES,
    ACCEPTABLE_EXCHANGES, EXCLUDED_EXCHANGES,
)
from src.analytics.indicators import IndicatorSnapshot
from src.diagnostics import DiagnosticsCollector


# Reason codes for diagnostics (mirror of codes in diagnostics.py)
REASON_EXCLUDED_ASSET_TYPE  = "excluded_asset_type"
REASON_EXCLUDED_EXCHANGE    = "excluded_exchange"
REASON_INACTIVE_SYMBOL      = "inactive_symbol"
REASON_PRICE_BELOW_MIN      = "liquidity_price_below_min"
REASON_AVG_VOL_BELOW_MIN    = "liquidity_avg_volume_below_min"
REASON_AVG_DVOL_BELOW_MIN   = "liquidity_dollar_volume_below_min"
REASON_SPREAD_TOO_WIDE      = "spread_too_wide"
REASON_CUR_DVOL_BELOW_MIN   = "current_dollar_volume_below_min"


@dataclass(frozen=True)
class FilterResult:
    """Outcome of hard-gate filtering."""
    passed: bool
    reason_code: str = ""
    detail: str = ""


def apply_hard_gates(
    ticker: str,
    snapshot: IndicatorSnapshot | None,
    metadata: SymbolMetadata,
    quote: Quote | None,
    cfg: Any,   # LiquidityV2Config
    diag: DiagnosticsCollector | None = None,
) -> FilterResult:
    """Apply hard-gate filters. Returns FilterResult.passed=True if OK.

    Args:
        ticker:   the symbol
        snapshot: indicator snapshot (may be None if too few bars)
        metadata: symbol metadata (exchange, type, market cap, float)
        quote:    latest bid/ask (may be None)
        cfg:      LiquidityV2Config from settings
        diag:     DiagnosticsCollector (optional)

    Returns:
        FilterResult with passed=True if the stock should continue to scanners.
    """

    def _reject(reason: str, detail: str) -> FilterResult:
        if diag:
            snap_str = ""
            if snapshot:
                snap_str = (
                    f"close=${snapshot.close:.2f} "
                    f"avgvol={snapshot.avg_volume_20:,.0f} "
                    f"dvol=${snapshot.dollar_volume_20:,.0f}"
                )
            diag.record(ticker=ticker, reason_code=reason, detail=detail,
                        snapshot_summary=snap_str)
        return FilterResult(passed=False, reason_code=reason, detail=detail)

    # 1. Asset type
    if metadata.asset_type in EXCLUDED_ASSET_TYPES:
        return _reject(REASON_EXCLUDED_ASSET_TYPE,
                        f"{metadata.asset_type} ({metadata.name or ticker})")
    if metadata.asset_type not in TRADABLE_ASSET_TYPES:
        # UNKNOWN asset type — could be OK (many providers don't classify),
        # so we don't hard-reject, we just let it through with lower scores.
        pass

    # 2. Exchange
    if metadata.exchange in EXCLUDED_EXCHANGES:
        return _reject(REASON_EXCLUDED_EXCHANGE,
                        f"exchange={metadata.exchange}")
    # Unknown exchange: don't reject (provider may not have info), penalize in score.

    # 3. Active
    if not metadata.is_active:
        return _reject(REASON_INACTIVE_SYMBOL, "symbol is inactive/delisted")

    # --- From here we need a snapshot ---
    if snapshot is None:
        return _reject("insufficient_bars", "snapshot not available (too few bars)")

    # 4. Price
    min_price = cfg.min_price
    if snapshot.close < min_price:
        return _reject(REASON_PRICE_BELOW_MIN,
                        f"${snapshot.close:.2f} < ${min_price}")

    # 5. Average volume
    min_vol = cfg.min_avg_volume
    # If stock is in low-price zone ($5-$10), require stronger volume
    if cfg.min_price <= 5.0 or (5.0 <= snapshot.close < 10.0):
        min_vol = int(min_vol * cfg.low_price_volume_multiplier)
    if snapshot.avg_volume_20 < min_vol:
        return _reject(REASON_AVG_VOL_BELOW_MIN,
                        f"avg vol {snapshot.avg_volume_20:,.0f} < {min_vol:,.0f}")

    # 6. Average dollar volume
    if snapshot.dollar_volume_20 < cfg.min_avg_dollar_volume:
        return _reject(REASON_AVG_DVOL_BELOW_MIN,
                        f"avg $vol ${snapshot.dollar_volume_20:,.0f} < "
                        f"${cfg.min_avg_dollar_volume:,.0f}")

    # 7. Current-day dollar volume
    if cfg.min_current_dollar_volume > 0:
        current_dvol = snapshot.close * snapshot.volume
        if current_dvol < cfg.min_current_dollar_volume:
            return _reject(REASON_CUR_DVOL_BELOW_MIN,
                            f"today $vol ${current_dvol:,.0f} < "
                            f"${cfg.min_current_dollar_volume:,.0f}")

    # 8. Spread (optional — only if quote data available AND filter enabled)
    if quote is not None and cfg.apply_spread_filter:
        spread = quote.spread_pct
        if spread > cfg.max_spread_pct:
            return _reject(REASON_SPREAD_TOO_WIDE,
                            f"spread {spread:.3f}% > {cfg.max_spread_pct}%")

    return FilterResult(passed=True)
