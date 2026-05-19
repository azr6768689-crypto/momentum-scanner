"""
Universe builder.

Downloads ALL US-listed symbols from the Nasdaq Trader FTP directory,
classifies them (common stock / ETF / leveraged ETF / excluded), and
produces 5 CSV files under data/universe/.

Source: ftp.nasdaqtrader.com — free, public, no API key required.
Files used:
  - nasdaqtraded.txt: all symbols traded on NYSE, NASDAQ, AMEX, etc.

The system can also work in offline/demo mode by generating a synthetic
universe (for testing when network is unavailable).
"""

from __future__ import annotations

import csv
import io
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)


# =============================================================================
# Known leveraged/inverse ETF patterns
# =============================================================================
# These are keywords in ETF names that indicate leveraged or inverse products.
_LEVERAGED_KEYWORDS = [
    "2x", "3x", "-2x", "-3x",
    "ultra", "ultrashort", "ultrapro",
    "direxion", "proshares ultra", "proshares short",
    "leveraged", "inverse",
    "bull 2x", "bull 3x", "bear 2x", "bear 3x",
]

# Common leveraged/inverse tickers (supplements name-based detection)
_LEVERAGED_TICKERS: frozenset[str] = frozenset({
    "TQQQ", "SQQQ", "QLD", "QID",
    "SOXL", "SOXS",
    "SPXL", "SPXS", "UPRO", "SPXU",
    "TNA", "TZA",
    "FAS", "FAZ",
    "LABU", "LABD",
    "NUGT", "DUST",
    "JNUG", "JDST",
    "TECL", "TECS",
    "UDOW", "SDOW",
    "FNGU", "FNGD",
    "ERX", "ERY",
    "CURE", "DRIP",
    "NAIL", "DRV",
    "YANG", "YINN",
    "TMF", "TMV",
    "UCO", "SCO",
    "AGQ", "ZSL",
    "UVXY", "SVXY", "VXX",
    "SOXS", "SOXL",
})

# Symbol suffix patterns that indicate non-common-stock security types
_JUNK_SUFFIX_PATTERNS = [
    r'\.W[A-Z]?$',   # warrants (.WS, .W, .WI)
    r'\.R$',          # rights
    r'\.U$',          # units
    r'\.P$',          # preferred (sometimes)
    r'[- ]WS$',       # warrants alt format
    r'\+$',           # when issued
]

_JUNK_PATTERNS_COMPILED = [re.compile(p, re.IGNORECASE) for p in _JUNK_SUFFIX_PATTERNS]


# =============================================================================
# Download from Nasdaq Trader FTP
# =============================================================================

def _download_nasdaq_traded(cache_dir: Path, cache_hours: int) -> pd.DataFrame:
    """Download nasdaqtraded.txt from ftp.nasdaqtrader.com.

    The file is pipe-delimited and contains ALL securities (stocks, ETFs,
    warrants, test issues, etc.) traded on major US exchanges.

    Returns a DataFrame with columns from the file, or raises on failure.
    Caches the raw file to avoid re-downloading within cache_hours.
    """
    import requests  # imported here so the module is importable without network

    cache_file = cache_dir / "nasdaqtraded_raw.txt"

    # Use cache if fresh
    if cache_file.exists():
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_hours < cache_hours:
            log.info("Using cached nasdaqtraded.txt (%.1fh old, cache=%dh)", age_hours, cache_hours)
            return _parse_nasdaq_traded(cache_file.read_text(encoding="latin-1"))

    # Download
    url = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true"
    # Fallback: the classic FTP-based URL via HTTP mirror
    trader_url = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"
    ftp_url = "https://ftp.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"

    log.info("Downloading symbol list from Nasdaq Trader...")
    for attempt_url in [trader_url, ftp_url]:
        try:
            resp = requests.get(attempt_url, timeout=60, headers={
                "User-Agent": "momentum-system/0.1",
            })
            if resp.status_code == 200 and len(resp.text) > 1000:
                cache_dir.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(resp.text, encoding="latin-1")
                log.info("Downloaded %d bytes from %s", len(resp.text), attempt_url)
                return _parse_nasdaq_traded(resp.text)
        except Exception as exc:
            log.warning("Failed to download from %s: %s", attempt_url, exc)

    raise RuntimeError(
        "Failed to download the Nasdaq Trader symbol list. "
        "Check your network connection or use universe.mode=starter for offline testing."
    )


def _parse_nasdaq_traded(raw_text: str) -> pd.DataFrame:
    """Parse the pipe-delimited nasdaqtraded.txt file.

    The file has a header row and a trailing metadata row.
    Columns include: Nasdaq Traded, Symbol, Security Name, Listing Exchange,
    Market Category, ETF, Round Lot Size, Test Issue, Financial Status, etc.
    """
    lines = raw_text.strip().split("\n")
    # Remove trailing metadata line (starts with date or "File Creation")
    if lines and (lines[-1].startswith("File") or lines[-1].startswith("Created")):
        lines = lines[:-1]

    reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter="|")
    rows = list(reader)
    if not rows:
        raise RuntimeError("nasdaqtraded.txt parsed to zero rows")

    df = pd.DataFrame(rows)

    # Clean column names (strip whitespace)
    df.columns = [c.strip() for c in df.columns]

    log.info("Parsed %d symbols from nasdaqtraded.txt (%d columns)",
             len(df), len(df.columns))
    return df


# =============================================================================
# Classification
# =============================================================================

def _is_test_issue(row: dict) -> bool:
    """Check if a symbol is a test issue."""
    return str(row.get("Test Issue", "")).strip().upper() == "Y"


def _is_etf(row: dict) -> bool:
    """Check if a symbol is an ETF."""
    return str(row.get("ETF", "")).strip().upper() == "Y"


def _is_leveraged_etf(symbol: str, name: str) -> bool:
    """Check if an ETF is leveraged/inverse."""
    if symbol.upper() in _LEVERAGED_TICKERS:
        return True
    name_lower = name.lower()
    for kw in _LEVERAGED_KEYWORDS:
        if kw in name_lower:
            return True
    return False


def _is_junk_symbol(symbol: str) -> bool:
    """Check if the symbol has a suffix indicating warrant/right/unit/preferred."""
    for pat in _JUNK_PATTERNS_COMPILED:
        if pat.search(symbol):
            return True
    return False


def _is_junk_security_name(name: str) -> bool:
    """Check security-name text for non-common share classes."""
    name_lower = name.lower()
    junk_terms = (
        " warrant",
        " warrants",
        " right",
        " rights",
        " unit",
        " units",
        " preferred",
        " preference",
    )
    return any(term in name_lower for term in junk_terms)


def _map_exchange(row: dict) -> str:
    """Map Nasdaq Trader exchange codes to our taxonomy."""
    listing = str(row.get("Listing Exchange", "")).strip().upper()
    mapping = {
        "N": "NYSE",
        "Q": "NASDAQ",
        "A": "AMEX",
        "P": "ARCA",
        "Z": "BATS",
        "V": "OTC",  # IEXG
    }
    return mapping.get(listing, "UNKNOWN")


# =============================================================================
# Build the universe
# =============================================================================

def build_universe(
    settings: Any,
    output_dir: Path | None = None,
    offline: bool = False,
) -> dict[str, Any]:
    """Build the full US symbol universe.

    Steps:
    1. Download all US-listed symbols from Nasdaq Trader
    2. Exclude test issues, junk symbols, OTC/pink
    3. Classify: common stock / ETF / leveraged ETF
    4. Save 5 CSV files
    5. Return stats dict

    Args:
        settings: Settings object with universe_cfg
        output_dir: override output directory (defaults to data/universe/)
        offline: if True, generate a synthetic universe (for testing)

    Returns:
        dict with stats and file paths
    """
    from src.config import PROJECT_ROOT, DATA_DIR

    ucfg = settings.universe_cfg
    out = output_dir or (DATA_DIR / "universe")
    out.mkdir(parents=True, exist_ok=True)
    cache_dir = DATA_DIR / "universe"

    stats = {
        "total_downloaded": 0,
        "excluded_test_issues": 0,
        "excluded_junk_symbols": 0,
        "excluded_otc": 0,
        "excluded_inactive": 0,
        "common_stocks": 0,
        "etfs": 0,
        "leveraged_etfs": 0,
        "final_universe": 0,
    }

    # --- Step 1: Get raw data ---
    if offline:
        df = _generate_offline_universe()
        log.info("Using offline/synthetic universe: %d rows", len(df))
    else:
        df = _download_nasdaq_traded(cache_dir, ucfg.cache_hours)

    stats["total_downloaded"] = len(df)

    # Save all_us_symbols.csv (raw)
    df.to_csv(out / ucfg.file_all_us, index=False, encoding="utf-8")

    # --- Step 2: Exclusions ---
    keep = []
    for _, row in df.iterrows():
        row_d = row.to_dict()
        symbol = str(row_d.get("Symbol", "")).strip().upper()

        if not symbol or len(symbol) > 10:
            continue

        # Test issue
        if _is_test_issue(row_d):
            stats["excluded_test_issues"] += 1
            continue

        name = str(row_d.get("Security Name", "")).strip()

        # Junk suffix/name (warrant, right, unit, preferred)
        if _is_junk_symbol(symbol) or _is_junk_security_name(name):
            stats["excluded_junk_symbols"] += 1
            continue

        # Exchange
        exchange = _map_exchange(row_d)
        if exchange in {"OTC", "UNKNOWN"}:
            stats["excluded_otc"] += 1
            continue

        # Financial status (deficient)
        fin_status = str(row_d.get("Financial Status", "")).strip().upper()
        if fin_status in {"D", "E", "G", "H", "Q"}:  # deficient/delinquent
            stats["excluded_inactive"] += 1
            continue

        # Explicit exclusions
        if symbol in {t.upper() for t in ucfg.explicit_exclude}:
            continue

        keep.append({
            "symbol": symbol,
            "name": name,
            "exchange": exchange,
            "is_etf": _is_etf(row_d),
            "is_leveraged_etf": _is_leveraged_etf(symbol, name) if _is_etf(row_d) else False,
            "asset_type": "etf" if _is_etf(row_d) else "common_stock",
        })

    clean = pd.DataFrame(keep)
    if clean.empty:
        log.error("Universe build produced zero symbols after exclusions!")
        return stats

    # --- Step 3: Classify ---
    common = clean[~clean["is_etf"]].copy()
    etfs = clean[(clean["is_etf"]) & (~clean["is_leveraged_etf"])].copy()
    leveraged = clean[clean["is_leveraged_etf"]].copy()

    stats["common_stocks"] = len(common)
    stats["etfs"] = len(etfs)
    stats["leveraged_etfs"] = len(leveraged)

    # --- Step 4: Save classified CSVs ---
    common.to_csv(out / ucfg.file_common_stocks, index=False, encoding="utf-8")
    etfs.to_csv(out / ucfg.file_etfs, index=False, encoding="utf-8")
    leveraged.to_csv(out / ucfg.file_leveraged_etfs, index=False, encoding="utf-8")

    # --- Step 5: Build final universe ---
    final_parts = [common]
    if ucfg.include_etfs:
        final_parts.append(etfs)
    if ucfg.include_leveraged_etfs:
        final_parts.append(leveraged)

    final = pd.concat(final_parts, ignore_index=True)

    # Deduplicate by symbol
    final = final.drop_duplicates(subset="symbol", keep="first")

    # Cap
    if len(final) > ucfg.max_tickers_per_run:
        log.warning("Final universe %d exceeds max %d, truncating",
                     len(final), ucfg.max_tickers_per_run)
        final = final.head(ucfg.max_tickers_per_run)

    stats["final_universe"] = len(final)
    final.to_csv(out / ucfg.file_final, index=False, encoding="utf-8")

    log.info("Universe built: %d total → %d common stocks, %d ETFs, %d leveraged → %d final",
             stats["total_downloaded"], stats["common_stocks"], stats["etfs"],
             stats["leveraged_etfs"], stats["final_universe"])

    stats["files"] = {
        "all_us_symbols": str(out / ucfg.file_all_us),
        "us_common_stocks": str(out / ucfg.file_common_stocks),
        "us_etfs": str(out / ucfg.file_etfs),
        "us_leveraged_etfs": str(out / ucfg.file_leveraged_etfs),
        "final_universe": str(out / ucfg.file_final),
    }
    return stats


def load_final_universe(settings: Any) -> list[str]:
    """Load the ticker list from final_universe.csv.

    Returns a list of symbols. If the file doesn't exist, falls back to
    starter mode with a warning.
    """
    from src.config import DATA_DIR

    ucfg = settings.universe_cfg
    final_path = DATA_DIR / "universe" / ucfg.file_final

    if not final_path.exists():
        log.warning(
            "final_universe.csv not found at %s. "
            "Run 'python scripts/refresh_universe.py' first. "
            "Falling back to starter mode.",
            final_path,
        )
        return _load_starter_tickers(settings)

    df = pd.read_csv(final_path)
    if "symbol" not in df.columns:
        log.error("final_universe.csv missing 'symbol' column")
        return _load_starter_tickers(settings)

    tickers = df["symbol"].dropna().str.strip().str.upper().unique().tolist()
    log.info("Loaded %d tickers from final_universe.csv", len(tickers))
    return tickers


def _load_starter_tickers(settings: Any) -> list[str]:
    """Load tickers from the hand-picked lists in universe.yaml (starter mode)."""
    raw = settings.universe_raw
    lists = settings.active_universe_lists
    seen: set[str] = set()
    tickers: list[str] = []
    for list_name in lists:
        symbols = raw.get(list_name, [])
        if not isinstance(symbols, list):
            continue
        for sym in symbols:
            s = sym.upper().strip()
            if s and s not in seen:
                tickers.append(s)
                seen.add(s)
    return tickers


# =============================================================================
# Offline / synthetic universe (for testing without network)
# =============================================================================

def _generate_offline_universe() -> pd.DataFrame:
    """Generate a realistic synthetic universe of ~3000 symbols for testing.

    This mimics the shape of nasdaqtraded.txt so the builder logic exercises
    all classification branches.
    """
    import hashlib
    import numpy as np

    rng = np.random.default_rng(42)
    rows = []

    # Generate common stocks with realistic tickers
    exchanges = ["N", "Q", "A"]  # NYSE, NASDAQ, AMEX
    for i in range(2500):
        # Generate 1-5 letter ticker
        length = rng.choice([2, 3, 4, 4, 5])
        letters = [chr(rng.integers(65, 91)) for _ in range(length)]
        ticker = "".join(letters)
        exchange = exchanges[i % 3]
        rows.append({
            "Symbol": ticker,
            "Security Name": f"Demo Corp {ticker} Common Stock",
            "Listing Exchange": exchange,
            "ETF": "N",
            "Test Issue": "N",
            "Financial Status": "N",
        })

    # Add known real tickers for sanity
    real_stocks = [
        "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO",
        "JPM", "V", "MA", "UNH", "XOM", "JNJ", "PG", "LLY", "HD", "COST",
        "WMT", "ABBV", "BAC", "CVX", "KO", "PEP", "ORCL", "MRK", "CRM",
        "ADBE", "NFLX", "AMD", "GS", "CAT", "BA", "DIS", "CSCO",
    ]
    for sym in real_stocks:
        rows.append({
            "Symbol": sym,
            "Security Name": f"Demo {sym} Inc Common Stock",
            "Listing Exchange": "N" if len(sym) <= 3 else "Q",
            "ETF": "N",
            "Test Issue": "N",
            "Financial Status": "N",
        })

    # Add ETFs
    etf_names = [
        ("SPY", "SPDR S&P 500 ETF Trust"), ("QQQ", "Invesco QQQ Trust"),
        ("IWM", "iShares Russell 2000 ETF"), ("DIA", "SPDR Dow Jones ETF"),
        ("XLK", "Technology Select Sector SPDR"), ("XLF", "Financial Select Sector SPDR"),
        ("XLE", "Energy Select Sector SPDR"), ("XLV", "Health Care Select Sector"),
        ("SMH", "VanEck Semiconductor ETF"), ("GLD", "SPDR Gold Shares"),
    ]
    for sym, name in etf_names:
        rows.append({
            "Symbol": sym, "Security Name": name,
            "Listing Exchange": "P", "ETF": "Y",
            "Test Issue": "N", "Financial Status": "N",
        })

    # Add leveraged ETFs
    for sym in ["TQQQ", "SQQQ", "SOXL", "SOXS", "SPXL", "SPXS", "UPRO", "SPXU"]:
        rows.append({
            "Symbol": sym,
            "Security Name": f"ProShares Ultra/UltraShort {sym}",
            "Listing Exchange": "Q", "ETF": "Y",
            "Test Issue": "N", "Financial Status": "N",
        })

    # Add junk (warrants, test issues, OTC) — these SHOULD be filtered out
    for i in range(50):
        rows.append({
            "Symbol": f"JUNK{i}.WS",
            "Security Name": f"Junk Corp {i} Warrant",
            "Listing Exchange": "Q", "ETF": "N",
            "Test Issue": "N", "Financial Status": "N",
        })
    for i in range(20):
        rows.append({
            "Symbol": f"TEST{i}",
            "Security Name": f"Test Issue {i}",
            "Listing Exchange": "Q", "ETF": "N",
            "Test Issue": "Y", "Financial Status": "N",
        })
    for i in range(100):
        rows.append({
            "Symbol": f"OTC{i}",
            "Security Name": f"OTC Penny Stock {i}",
            "Listing Exchange": "V", "ETF": "N",
            "Test Issue": "N", "Financial Status": "N",
        })

    return pd.DataFrame(rows)
