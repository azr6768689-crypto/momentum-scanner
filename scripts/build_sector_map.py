#!/usr/bin/env python3
"""Build a local ticker-to-sector/industry map from Polygon reference details."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import ensure_directories, load_settings
from src.data import get_provider


def _load_symbols(path: Path) -> list[str]:
    df = pd.read_csv(path)
    symbol_col = "symbol" if "symbol" in df.columns else df.columns[0]
    symbols = [str(value).upper().strip() for value in df[symbol_col].dropna()]
    seen: set[str] = set()
    return [symbol for symbol in symbols if symbol and not (symbol in seen or seen.add(symbol))]


def _sector_from_details(details: dict) -> str:
    # Polygon currently exposes SIC description more reliably than GICS sector.
    for key in ["sic_description", "industry", "market"]:
        value = details.get(key)
        if value:
            return str(value).strip()
    return "לא זמין"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build sector map from Polygon ticker details")
    parser.add_argument("--universe-csv", type=Path, default=ROOT / "data" / "universe" / "polygon_liquid_us.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "universe" / "sector_map.csv")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    settings = load_settings()
    ensure_directories(settings)
    provider = get_provider(settings)
    if not hasattr(provider, "get_ticker_details"):
        raise RuntimeError("Current provider cannot fetch ticker details. Use DATA_PROVIDER=polygon.")

    symbols = _load_symbols(args.universe_csv)
    if args.limit:
        symbols = symbols[:args.limit]

    existing = pd.DataFrame()
    done: set[str] = set()
    if args.output.exists():
        existing = pd.read_csv(args.output)
        if "symbol" in existing.columns:
            done = set(existing["symbol"].astype(str).str.upper())

    rows: list[dict] = [] if existing.empty else existing.to_dict("records")
    for idx, symbol in enumerate(symbols, start=1):
        if symbol in done:
            continue
        try:
            details = provider.get_ticker_details(symbol)
        except Exception as exc:
            logging.warning("Skip details for %s: %s", symbol, exc)
            details = {}
        rows.append({
            "symbol": symbol,
            "name": details.get("name", ""),
            "sector": _sector_from_details(details),
            "sic_code": details.get("sic_code", ""),
            "sic_description": details.get("sic_description", ""),
        })
        if idx % 100 == 0 or idx == len(symbols):
            logging.info("Mapped %d/%d symbols", idx, len(symbols))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(rows).drop_duplicates("symbol", keep="last").to_csv(args.output, index=False)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out = pd.DataFrame(rows).drop_duplicates("symbol", keep="last")
    out.to_csv(args.output, index=False)
    print("sector_map_status=ok")
    print(f"symbols={len(symbols)}")
    print(f"mapped={len(out)}")
    print(f"file={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
