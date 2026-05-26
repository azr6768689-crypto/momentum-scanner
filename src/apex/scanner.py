"""Apex universe scan orchestration."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import pandas as pd

from src.apex.features import chart_payload, compute_features, relative_return
from src.apex.market import build_market_context
from src.apex.models import ApexScanResult, MarketContext
from src.apex.scorer import rs_percentile, score_stock
from src.scan_progress import write_progress
from src.scan_runtime import cap_scan_workers


def _data_source_label() -> str:
    p = os.getenv("DATA_PROVIDER", "demo").strip().lower()
    return {
        "demo": "דמו (סינתטי)",
        "polygon": "Polygon",
        "tiingo": "Tiingo",
    }.get(p, p)


class ApexScanner:
    def __init__(
        self,
        universe: dict[str, pd.DataFrame],
        sector_map: dict[str, str] | None = None,
        *,
        include_charts: bool = True,
        chart_bars: int = 90,
    ) -> None:
        self.universe = universe
        self.sector_map = sector_map or {}
        self.include_charts = include_charts
        self.chart_bars = chart_bars
        self.market = build_market_context(
            universe.get("SPY"),
            universe.get("QQQ"),
            universe.get("IWM"),
        )
        self.spy = universe.get("SPY")
        self.qqq = universe.get("QQQ")
        self.data_source = _data_source_label()

    def _rs_map(self, tickers: list[str]) -> dict[str, int]:
        raw: dict[str, float] = {}
        for t in tickers:
            df = self.universe.get(t)
            if df is None or len(df) < 25:
                continue
            raw[t] = relative_return(df, self.spy, 20)
        return rs_percentile(raw)

    def _scan_one(self, ticker: str, rs_rating: int) -> ApexScanResult | None:
        df = self.universe.get(ticker)
        if df is None:
            return None
        f = compute_features(df)
        if f is None:
            return None

        scored = score_stock(
            ticker,
            f,
            rs_rating=rs_rating,
            market=self.market,
            spy_df=self.spy,
            qqq_df=self.qqq,
            stock_df=df,
        )

        charts = chart_payload(df, self.chart_bars) if self.include_charts else []

        return ApexScanResult(
            ticker=ticker,
            sector=self.sector_map.get(ticker, "לא זמין"),
            data_source=self.data_source,
            apex_score=scored["apex_score"],
            rs_rating=rs_rating,
            trend_grade=scored["trend_grade"],
            setup_type=scored["setup_type"],
            institutional_grade=scored["institutional_grade"],
            timing_score=scored["timing_score"],
            volume_score=scored["volume_score"],
            risk_reward=scored["risk_reward"],
            last_close=f.close,
            pct_change_1d=f.pct_1d,
            rvol=f.rvol,
            dist_52w_high_pct=f.dist_52w,
            rs_vs_spy_20d=scored["rs_vs_spy_20d"],
            rs_vs_qqq_20d=scored["rs_vs_qqq_20d"],
            market_regime=self.market.regime,
            market_score=self.market.score,
            sma20=f.sma20,
            sma50=f.sma50,
            sma200=f.sma200,
            atr14=f.atr14,
            rsi14=f.rsi14,
            adx14=f.adx14,
            entry=scored["entry"],
            stop=scored["stop"],
            target_1=scored["target_1"],
            target_2=scored["target_2"],
            trigger=scored["trigger"],
            summary=scored["summary"],
            flags=scored["flags"],
            chart_ohlcv=charts,
        )

    def scan(self, tickers: list[str], *, workers: int | None = None) -> list[ApexScanResult]:
        rs_map = self._rs_map(tickers)
        workers_n = cap_scan_workers(workers or 8)
        total = len(tickers)
        results: list[ApexScanResult] = []

        if total >= 80 and workers_n > 1:
            with ThreadPoolExecutor(max_workers=workers_n) as pool:
                futs = {
                    pool.submit(self._scan_one, t, rs_map.get(t, 50)): t for t in tickers
                }
                done = 0
                for fut in as_completed(futs):
                    r = fut.result()
                    done += 1
                    if r is not None:
                        results.append(r)
                    if done == 1 or done % 50 == 0 or done == total:
                        write_progress(
                            72 + int(22 * done / max(total, 1)),
                            "דירוג",
                            done=done,
                            total=total,
                            message=f"Apex: מדרג {done:,}/{total:,}",
                        )
        else:
            for i, t in enumerate(tickers, 1):
                r = self._scan_one(t, rs_map.get(t, 50))
                if r is not None:
                    results.append(r)
                if i == 1 or i % 50 == 0 or i == total:
                    write_progress(
                        72 + int(22 * i / max(total, 1)),
                        "דירוג",
                        done=i,
                        total=total,
                        message=f"Apex: מדרג {i:,}/{total:,}",
                    )

        results.sort(
            key=lambda x: (x.apex_score, x.rs_rating, x.rvol),
            reverse=True,
        )
        return results


def scan_universe(
    tickers: list[str],
    universe: dict[str, pd.DataFrame],
    sector_map: dict[str, str] | None = None,
) -> list[ApexScanResult]:
    return ApexScanner(universe, sector_map).scan(tickers)
