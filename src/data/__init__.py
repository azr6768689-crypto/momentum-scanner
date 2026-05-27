"""Data layer package.

Public API:
    get_provider(settings) -> DataProvider
        Returns the configured provider instance based on settings.provider.

    DataProvider, ProviderError, etc. (re-exported from .base)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .base import (
    DataProvider,
    ProviderError,
    RateLimitError,
    SymbolNotFoundError,
    OHLCV_COLUMNS,
)
from .demo_provider import DemoProvider

if TYPE_CHECKING:
    from ..config import Settings


log = logging.getLogger(__name__)


__all__ = [
    "get_provider",
    "DataProvider",
    "ProviderError",
    "RateLimitError",
    "SymbolNotFoundError",
    "OHLCV_COLUMNS",
]


def get_provider(settings: "Settings") -> DataProvider:
    """Return the data provider configured in settings.

    Centralizing this here means changing providers is a one-liner in .env.
    If a non-demo provider fails to initialize (e.g. missing key) we raise
    a clear error rather than silently falling back — silent fallbacks
    cause confusing bugs later.
    """
    p = settings.provider.lower().strip()

    if p == "demo":
        log.info("Using DemoProvider (no API key, synthetic data).")
        return DemoProvider()

    if p == "tiingo":
        # Defer import so missing optional deps don't break demo mode
        from .tiingo_provider import TiingoProvider

        key = settings.get_tiingo_key()
        rl = settings.data.rate_limits.get("tiingo")
        log.info("Using TiingoProvider.")
        return TiingoProvider(
            api_key=key,
            cache_dir=settings.data.cache_dir,
            cache_ttl_hours=settings.data.cache_ttl_hours,
            cache_enabled=settings.data.cache_enabled,
            requests_per_hour=(rl.requests_per_hour if rl else 800),
            requests_per_second=(rl.requests_per_second if rl else 5),
            retry_max_attempts=settings.data.retry_max_attempts,
            retry_initial_backoff=settings.data.retry_initial_backoff,
            retry_max_backoff=settings.data.retry_max_backoff,
        )

    if p == "polygon":
        from .polygon_provider import PolygonProvider

        key = settings.get_polygon_key()
        rl = settings.data.rate_limits.get("polygon")
        log.info("Using PolygonProvider.")
        return PolygonProvider(
            api_key=key,
            cache_dir=settings.data.cache_dir,
            cache_ttl_hours=settings.data.cache_ttl_hours,
            cache_enabled=settings.data.cache_enabled,
            retry_max_attempts=settings.data.retry_max_attempts,
            retry_initial_backoff=settings.data.retry_initial_backoff,
            retry_max_backoff=settings.data.retry_max_backoff,
            requests_per_minute=(rl.requests_per_minute if rl else 0),
        )

    if p == "alpaca":
        raise NotImplementedError(
            "Alpaca provider is scaffolded for Phase 2. "
            "For now use DATA_PROVIDER=demo or DATA_PROVIDER=tiingo."
        )

    raise ValueError(f"Unknown provider: {p!r}")
