"""Alert rules and evaluation — Trade Ideas-style triggers."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
ALERTS_PATH = ROOT / "data" / "alerts" / "events.json"
RULES_PATH = ROOT / "data" / "alerts" / "rules.json"


@dataclass
class AlertRule:
    id: str
    name: str
    enabled: bool = True
    # price_above | rvol_ge | pct_day_ge | new_hod | apex_score_ge
    kind: str = "price_above"
    symbol: str = ""
    threshold: float = 0.0
    note: str = ""


@dataclass
class AlertEvent:
    id: str
    rule_id: str
    symbol: str
    message: str
    created_at: str
    payload: dict[str, Any] = field(default_factory=dict)


def _ensure_dirs() -> None:
    ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)


def load_rules() -> list[AlertRule]:
    _ensure_dirs()
    if not RULES_PATH.is_file():
        return _default_rules()
    try:
        raw = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _default_rules()
    out: list[AlertRule] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict):
            out.append(AlertRule(**{k: item[k] for k in AlertRule.__dataclass_fields__ if k in item}))
    return out or _default_rules()


def save_rules(rules: list[AlertRule]) -> None:
    _ensure_dirs()
    RULES_PATH.write_text(
        json.dumps([asdict(r) for r in rules], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _default_rules() -> list[AlertRule]:
    return [
        AlertRule(
            id="default-rvol",
            name="RVOL תוך-יומי ≥ 2",
            kind="rvol_ge",
            threshold=2.0,
            symbol="*",
            note="כל מניה ב-watchlist",
        ),
        AlertRule(
            id="default-pct",
            name="עלייה יומית ≥ 3%",
            kind="pct_day_ge",
            threshold=3.0,
            symbol="*",
        ),
    ]


def load_alerts(limit: int = 200) -> list[AlertEvent]:
    _ensure_dirs()
    if not ALERTS_PATH.is_file():
        return []
    try:
        raw = json.loads(ALERTS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    events: list[AlertEvent] = []
    for item in (raw if isinstance(raw, list) else [])[-limit:]:
        if isinstance(item, dict):
            events.append(AlertEvent(**{k: item[k] for k in AlertEvent.__dataclass_fields__ if k in item}))
    return list(reversed(events))


def save_alerts(events: list[AlertEvent], keep: int = 500) -> None:
    _ensure_dirs()
    trimmed = events[-keep:]
    ALERTS_PATH.write_text(
        json.dumps([asdict(e) for e in trimmed], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class AlertEngine:
    def __init__(self, rules: list[AlertRule] | None = None) -> None:
        self.rules = rules if rules is not None else load_rules()

    def evaluate_symbol(
        self,
        symbol: str,
        *,
        last: float,
        pct_day: float,
        rvol: float,
        high_of_day: float,
        apex_score: float | None = None,
        trigger_price: float | None = None,
    ) -> list[AlertEvent]:
        fired: list[AlertEvent] = []
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        sym = symbol.upper()

        for rule in self.rules:
            if not rule.enabled:
                continue
            if rule.symbol not in ("*", "") and rule.symbol.upper() != sym:
                continue

            hit = False
            msg = ""
            if rule.kind == "price_above" and trigger_price and last >= trigger_price:
                hit = True
                msg = f"{sym} מעל טריגר ${trigger_price:.2f} (עכשיו ${last:.2f})"
            elif rule.kind == "rvol_ge" and rvol >= rule.threshold:
                hit = True
                msg = f"{sym} RVOL תוך-יומי {rvol:.1f}x ≥ {rule.threshold}"
            elif rule.kind == "pct_day_ge" and pct_day >= rule.threshold:
                hit = True
                msg = f"{sym} עלייה יומית {pct_day:.1f}% ≥ {rule.threshold}%"
            elif rule.kind == "new_hod" and last >= high_of_day * 0.999 and high_of_day > 0:
                hit = True
                msg = f"{sym} שיא יומי חדש ${last:.2f}"
            elif rule.kind == "apex_score_ge" and apex_score is not None and apex_score >= rule.threshold:
                hit = True
                msg = f"{sym} Apex Score {apex_score:.0f} ≥ {rule.threshold:.0f}"

            if hit:
                fired.append(
                    AlertEvent(
                        id=str(uuid.uuid4())[:8],
                        rule_id=rule.id,
                        symbol=sym,
                        message=msg,
                        created_at=now,
                        payload={
                            "last": last,
                            "pct_day": pct_day,
                            "rvol": rvol,
                            "apex_score": apex_score,
                        },
                    )
                )
        return fired

    def merge_events(self, new_events: list[AlertEvent]) -> list[AlertEvent]:
        existing = load_alerts(limit=500)
        combined = new_events + existing
        save_alerts(combined)
        return combined
