"""Tests for Apex momentum scanner."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from src.apex.features import compute_features
from src.apex.patterns import detect_setup
from src.apex.scanner import ApexScanner
from src.data.demo_provider import DemoProvider


def _demo_df(symbol: str = "TEST") -> pd.DataFrame:
    p = DemoProvider()
    end = date.today()
    start = end - timedelta(days=400)
    return p.get_daily_bars(symbol, start, end)


def test_compute_features_not_empty():
    df = _demo_df("AAPL")
    f = compute_features(df)
    assert f is not None
    assert f.close > 0
    assert 0 <= f.rsi14 <= 100


def test_detect_setup_returns_label():
    df = _demo_df("NVDA")
    f = compute_features(df)
    assert f is not None
    label, _ = detect_setup(f)
    assert isinstance(label, str) and len(label) > 0


def test_scanner_produces_ranked_results():
    tickers = ["AAA", "BBB", "CCC"]
    universe = {t: _demo_df(t) for t in tickers}
    for b in ("SPY", "QQQ", "IWM"):
        universe[b] = _demo_df(b)
    results = ApexScanner(universe, include_charts=False).scan(tickers)
    assert len(results) == 3
    assert results[0].apex_score >= results[-1].apex_score
