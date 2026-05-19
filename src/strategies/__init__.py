"""Strategies package.

build_strategies(strategies_yaml) -> list[BaseStrategy]
    Reads config/strategies.yaml and instantiates all enabled strategies.
"""

from __future__ import annotations

from typing import Any

from .base import (
    BaseStrategy, SetupSignal,
    STATUS_WATCH, STATUS_TRIGGER, STATUS_WAIT, STATUS_IGNORE, STATUS_INVALIDATED,
    SCANNER_PRE_BREAKOUT, SCANNER_BREAKOUT, SCANNER_CONTINUATION,
)
from .pre_breakout_compression import PreBreakoutCompressionStrategy
from .breakout_highs import (
    BreakoutHighsStrategy,
    create_breakout_20d,
    create_breakout_50d,
    create_breakout_52w,
)
from .bull_flag_continuation import BullFlagContinuationStrategy
from .pullback_after_momentum import PullbackAfterMomentumStrategy


def build_strategies(strategies_yaml: dict[str, Any]) -> list[BaseStrategy]:
    """Instantiate all strategy modules from YAML config.

    Only returns enabled strategies. Disabled ones are silently skipped.
    """
    registry: list[BaseStrategy] = []

    # Pre-breakout compression
    p = strategies_yaml.get("pre_breakout_compression", {})
    s = PreBreakoutCompressionStrategy(p)
    if s.is_enabled():
        registry.append(s)

    # Breakout variants
    for key, factory in [
        ("breakout_20d", create_breakout_20d),
        ("breakout_50d", create_breakout_50d),
        ("breakout_52w", create_breakout_52w),
    ]:
        p = strategies_yaml.get(key, {})
        s = factory(p)
        if s.is_enabled():
            registry.append(s)

    # Bull flag
    p = strategies_yaml.get("bull_flag", {})
    s = BullFlagContinuationStrategy(p)
    if s.is_enabled():
        registry.append(s)

    # Pullback after momentum
    p = strategies_yaml.get("pullback_after_momentum", {})
    s = PullbackAfterMomentumStrategy(p)
    if s.is_enabled():
        registry.append(s)

    return registry


__all__ = [
    "build_strategies",
    "BaseStrategy",
    "SetupSignal",
    "STATUS_WATCH", "STATUS_TRIGGER", "STATUS_WAIT", "STATUS_IGNORE", "STATUS_INVALIDATED",
    "SCANNER_PRE_BREAKOUT", "SCANNER_BREAKOUT", "SCANNER_CONTINUATION",
]
