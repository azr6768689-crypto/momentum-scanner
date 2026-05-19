"""
Base classes for strategy modules.

Every strategy implements:
    class XYZStrategy(BaseStrategy):
        name = "xyz"
        scanner_mode = "pre_breakout" | "breakout" | "continuation"
        setup_type = "Human readable name"

        def detect(self, ticker, df, snapshot) -> SetupSignal | None

Returns SetupSignal on match, None otherwise.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Any

import pandas as pd

from src.analytics.indicators import IndicatorSnapshot


# --- Status taxonomy -------------------------------------------------------
STATUS_WATCH       = "Watch"
STATUS_TRIGGER     = "Trigger"
STATUS_WAIT        = "Wait for pullback"
STATUS_IGNORE      = "Ignore"
STATUS_INVALIDATED = "Invalidated"

VALID_STATUSES = {STATUS_WATCH, STATUS_TRIGGER, STATUS_WAIT, STATUS_IGNORE, STATUS_INVALIDATED}

# --- Scanner modes ----------------------------------------------------------
SCANNER_PRE_BREAKOUT = "pre_breakout"
SCANNER_BREAKOUT     = "breakout"
SCANNER_CONTINUATION = "continuation"


@dataclass
class SetupSignal:
    """Structured output from a strategy module."""

    ticker: str
    setup_type: str
    strategy_module: str
    scanner_mode: str
    status: str

    entry_trigger: float
    stop_loss: float
    target_1: float
    target_2: float
    risk_reward: float

    reason: str
    invalidation: str

    score_hint: int = 0
    warnings: list[str] = field(default_factory=list)
    factor_inputs: dict[str, Any] = field(default_factory=dict)
    wait_for: str = ""
    as_of: pd.Timestamp | None = None

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{self.status}' for {self.ticker}")
        if self.stop_loss >= self.entry_trigger:
            raise ValueError(
                f"{self.ticker}: stop ({self.stop_loss}) must be < entry ({self.entry_trigger})"
            )
        if self.target_1 <= self.entry_trigger:
            raise ValueError(
                f"{self.ticker}: target_1 ({self.target_1}) must be > entry ({self.entry_trigger})"
            )
        if self.target_2 < self.target_1:
            raise ValueError(
                f"{self.ticker}: target_2 ({self.target_2}) must be >= target_1 ({self.target_1})"
            )
        self.score_hint = max(0, min(100, int(self.score_hint)))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.as_of is not None:
            d["as_of"] = self.as_of.isoformat()
        return d

    @staticmethod
    def calc_risk_reward(entry: float, stop: float, target: float) -> float:
        downside = entry - stop
        if downside <= 0:
            return 0.0
        return (target - entry) / downside


class BaseStrategy(ABC):
    name: str = "abstract"
    scanner_mode: str = ""
    setup_type: str = ""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params = params or {}

    @abstractmethod
    def detect(
        self,
        ticker: str,
        df: pd.DataFrame,
        snapshot: IndicatorSnapshot,
    ) -> SetupSignal | None:
        """Return SetupSignal or None."""

    def p(self, key: str, default: Any = None) -> Any:
        return self.params.get(key, default)

    def is_enabled(self) -> bool:
        return bool(self.params.get("enabled", False))
