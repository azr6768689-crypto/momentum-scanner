"""Scanners package."""

from __future__ import annotations

from typing import Any

from src.strategies.base import BaseStrategy
from src.diagnostics import DiagnosticsCollector
from .base import BaseScanner
from .pre_breakout import PreBreakoutScanner
from .breakout import BreakoutScanner
from .continuation import ContinuationScanner


def build_scanners(
    strategies: list[BaseStrategy],
    settings: Any,
    diagnostics: DiagnosticsCollector | None = None,
) -> list[BaseScanner]:
    """Instantiate all three scanner modes, sharing the same diagnostics collector."""
    return [
        PreBreakoutScanner(strategies, settings, diagnostics=diagnostics),
        BreakoutScanner(strategies, settings, diagnostics=diagnostics),
        ContinuationScanner(strategies, settings, diagnostics=diagnostics),
    ]


__all__ = [
    "build_scanners",
    "BaseScanner",
    "PreBreakoutScanner",
    "BreakoutScanner",
    "ContinuationScanner",
]
