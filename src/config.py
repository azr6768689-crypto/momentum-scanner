"""
Central configuration loader.

Responsibilities:
- Load settings.yaml, universe.yaml, strategies.yaml from config/
- Load .env (API keys, provider mode)
- Provide a single Settings object that the rest of the system imports
- Never expose raw API keys in logs

Usage:
    from src.config import load_settings
    settings = load_settings()
    print(settings.provider)            # e.g. "demo"
    print(settings.liquidity.min_price) # e.g. 10.0
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


# =============================================================================
# Path resolution
# =============================================================================
# This file lives at <project_root>/src/config.py
# So <project_root> = parent of parent of this file.
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
CONFIG_DIR: Path = PROJECT_ROOT / "config"
DATA_DIR: Path = PROJECT_ROOT / "data"
LOGS_DIR: Path = PROJECT_ROOT / "logs"


# =============================================================================
# Dataclasses — typed views over YAML sections
# =============================================================================
# Using dataclasses (not raw dicts) gives us:
#   1. autocomplete in editors
#   2. early failure if a config key goes missing
#   3. self-documenting code

@dataclass(frozen=True)
class UniverseConfig:
    """Universe selection configuration."""
    mode: str                    # "full_liquid_us_stocks" | "starter"
    include_etfs: bool
    include_leveraged_etfs: bool
    source: str                  # "nasdaq_trader" | "provider"
    max_tickers_per_run: int
    cache_hours: int
    recent_ipos_days: int
    explicit_exclude: list[str]
    starter_lists: list[str]
    # File paths (relative names under data/universe/)
    file_all_us: str
    file_common_stocks: str
    file_etfs: str
    file_leveraged_etfs: str
    file_final: str


@dataclass(frozen=True)
class LiquidityFilters:
    min_price: float
    min_avg_volume_20d: int
    min_avg_dollar_volume_20d: float


@dataclass(frozen=True)
class TrendFilters:
    require_close_above_sma20: bool
    require_close_above_sma50: bool
    require_sma20_above_sma50: bool
    require_sma50_rising: bool
    sma50_slope_lookback_bars: int


@dataclass(frozen=True)
class RelativeStrengthFilters:
    benchmark_primary: str
    benchmark_secondary: str
    lookback_windows_days: list[int]
    require_positive_vs_primary_20d: bool
    require_positive_vs_secondary_20d: bool


@dataclass(frozen=True)
class VolumeFilters:
    rvol_lookback_days: int
    rvol_min_general: float
    rvol_min_breakout: float
    rvol_min_continuation_high_gain: float


@dataclass(frozen=True)
class RiskRewardFilters:
    min_rr_to_target_1: float
    max_stop_distance_atr: float
    min_resistance_distance_atr: float
    atr_period: int


@dataclass(frozen=True)
class ExtensionFilters:
    max_pct_above_vwap: float
    max_atr_above_sma20: float
    max_day_gain_pct_no_setup: float


@dataclass(frozen=True)
class ContinuationFilters:
    day_gain_pct_min: float
    day_gain_pct_preferred_max: float
    day_gain_pct_absolute_max: float


@dataclass(frozen=True)
class LiquidityV2Config:
    """Full liquidity and tradability filter configuration (Group G)."""
    # Price
    min_price: float
    low_price_volume_multiplier: float
    # Volume
    min_avg_volume: int
    preferred_avg_volume: int
    # Dollar volume
    min_avg_dollar_volume: float
    preferred_avg_dollar_volume: float
    # Relative volume
    min_rvol_for_signals: float
    strong_rvol: float
    exceptional_rvol: float
    # Current-day dollar volume
    min_current_dollar_volume: float
    # Spread
    max_spread_pct: float
    warn_spread_pct: float
    apply_spread_filter: bool
    # Market cap / float
    min_market_cap: float
    warn_market_cap: float
    low_float_threshold: float
    # Score
    score_weights: dict[str, int]
    min_liquidity_score: int
    warn_liquidity_score: int


@dataclass(frozen=True)
class ScoringConfig:
    weights: dict[str, int]
    extension_penalty_max: int
    threshold_include: int
    threshold_strong: int
    threshold_elite: int


@dataclass(frozen=True)
class RateLimitConfig:
    requests_per_hour: int | None = None
    requests_per_minute: int | None = None
    requests_per_second: float | None = None


@dataclass(frozen=True)
class DataConfig:
    cache_dir: Path
    cache_ttl_hours: int
    cache_enabled: bool
    history_years: int
    rate_limits: dict[str, RateLimitConfig]
    retry_max_attempts: int
    retry_initial_backoff: float
    retry_max_backoff: float


@dataclass(frozen=True)
class ReportingConfig:
    output_dir: Path
    csv_filename_format: str
    watchlist_filename_format: str
    summary_filename_format: str
    diagnostics_filename_format: str
    rejected_filename_format: str
    top_n_in_summary: int
    include_invalidated_in_csv: bool


@dataclass(frozen=True)
class ReportMode:
    """Resolved report-mode preset (after picking active + overrides)."""
    active: str                       # "strict" | "balanced" | "exploratory"
    main_report_score: int            # >= this = Main Report
    watchlist_score: int              # between watchlist_score and main = Watchlist
    label_low_confidence: bool        # whether to mark all items as low-conf


@dataclass(frozen=True)
class Thresholds:
    """User-facing thresholds, the single source of truth."""
    main_report_score: int
    watchlist_score: int
    min_risk_reward: float
    max_distance_from_sma20: float
    max_atr_extension: float
    min_relative_volume: float


@dataclass(frozen=True)
class Settings:
    """The single object that holds all settings.

    Rest of the codebase imports this and reads attributes off it.
    No module should ever read YAML or .env directly.
    """

    # Provider selection — comes from .env (or override in settings.yaml)
    provider: str

    # API keys (kept private; we never log these)
    _tiingo_api_key: str
    _polygon_api_key: str
    _alpaca_api_key: str
    _alpaca_secret_key: str
    _alpaca_base_url: str

    # Logging
    log_level: str

    # Typed config sections
    data: DataConfig
    universe_cfg: UniverseConfig
    liquidity: LiquidityFilters
    trend: TrendFilters
    relative_strength: RelativeStrengthFilters
    volume: VolumeFilters
    risk_reward: RiskRewardFilters
    extension: ExtensionFilters
    continuation: ContinuationFilters
    scoring: ScoringConfig
    reporting: ReportingConfig
    report_mode: ReportMode
    thresholds: Thresholds
    liquidity_v2: LiquidityV2Config

    # Universe + strategies — raw dicts (kept for starter mode + strategy params)
    universe_raw: dict[str, Any]
    strategies_raw: dict[str, Any]

    # Active universe lists (starter mode only)
    active_universe_lists: list[str] = field(default_factory=list)

    # ---- Safe accessors for secrets ---------------------------------------
    def get_tiingo_key(self) -> str:
        if not self._tiingo_api_key:
            raise RuntimeError(
                "TIINGO_API_KEY is empty. Set it in .env or switch DATA_PROVIDER=demo."
            )
        return self._tiingo_api_key

    def get_polygon_key(self) -> str:
        if not self._polygon_api_key:
            raise RuntimeError(
                "POLYGON_API_KEY is empty. Set it in .env or use another provider."
            )
        return self._polygon_api_key


# =============================================================================
# Loader
# =============================================================================

def _read_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML file safely. Raises a clear error if missing/malformed."""
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            f"Expected location: {path.resolve()}\n"
            f"Have you created the config/ directory with the YAML files?"
        )
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise RuntimeError(f"Failed to parse YAML at {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"YAML at {path} must be a mapping at the top level.")
    return data


def _build_rate_limits(raw: dict[str, Any]) -> dict[str, RateLimitConfig]:
    """Convert the rate_limits YAML block to typed configs."""
    result: dict[str, RateLimitConfig] = {}
    for provider_name, limits in (raw or {}).items():
        result[provider_name] = RateLimitConfig(
            requests_per_hour=limits.get("requests_per_hour"),
            requests_per_minute=limits.get("requests_per_minute"),
            requests_per_second=limits.get("requests_per_second"),
        )
    return result


_VALID_DATA_PROVIDERS = frozenset({"demo", "tiingo", "polygon", "alpaca"})


def _load_polygon_api_key_for_settings() -> str:
    try:
        from src.polygon_key_store import resolve_polygon_api_key

        return resolve_polygon_api_key()
    except Exception:
        from src.env_secrets import clean_env_secret

        return clean_env_secret(os.getenv("POLYGON_API_KEY", "")) or clean_env_secret(
            os.getenv("MASSIVE_API_KEY", "")
        )


def _normalize_data_provider(raw: str | None) -> str:
    """Map DATA_PROVIDER to a known value; prefer Polygon when a key exists."""
    from src.polygon_key_store import resolve_polygon_api_key

    explicit = (raw or "").lower().strip()
    if explicit in _VALID_DATA_PROVIDERS:
        if explicit == "demo":
            return "demo"
        return explicit
    if resolve_polygon_api_key():
        return "polygon"
    if os.getenv("RENDER", "").strip().lower() in {"1", "true", "yes", "on"}:
        return "polygon"
    return "polygon" if os.getenv("POLYGON_API_KEY", "").strip() else "demo"


def load_settings(config_dir: Path | None = None) -> Settings:
    """Load and validate all configuration. Call this once at startup.

    Args:
        config_dir: optional override for the config directory location.
                    Defaults to <project_root>/config.

    Returns:
        A fully-populated Settings object.

    Raises:
        FileNotFoundError: a config file is missing.
        RuntimeError: a config file is malformed or a required key is missing.
    """
    cdir = config_dir or CONFIG_DIR

    # 1. Load .env first so environment variables are available.
    #    override=True ensures a manual edit to the project .env is picked up
    #    even if the shell already has an older exported value.
    env_path = PROJECT_ROOT / ".env"
    # Never wipe keys injected by Render / scan subprocess (override only unset vars).
    load_dotenv(env_path, override=False)

    # 2. Read YAML files
    settings_yaml = _read_yaml(cdir / "settings.yaml")
    universe_yaml = _read_yaml(cdir / "universe.yaml")
    strategies_yaml = _read_yaml(cdir / "strategies.yaml")

    # 3. Resolve provider: .env wins unless settings.yaml has an explicit override
    provider_override = (settings_yaml.get("data") or {}).get("provider_override")
    provider = _normalize_data_provider(
        provider_override or os.getenv("DATA_PROVIDER", "demo")
    )

    # 4. Build typed sections
    data_block = settings_yaml["data"]
    data_cfg = DataConfig(
        cache_dir=(PROJECT_ROOT / data_block["cache_dir"]).resolve(),
        cache_ttl_hours=int(data_block["cache_ttl_hours"]),
        cache_enabled=bool(data_block["cache_enabled"]),
        history_years=int(data_block["history_years"]),
        rate_limits=_build_rate_limits(data_block.get("rate_limits", {})),
        retry_max_attempts=int(data_block["retry"]["max_attempts"]),
        retry_initial_backoff=float(data_block["retry"]["initial_backoff_seconds"]),
        retry_max_backoff=float(data_block["retry"]["max_backoff_seconds"]),
    )

    # --- Universe config ---
    u_block = settings_yaml.get("universe") or {}
    excl_block = u_block.get("exclude") or {}
    files_block = u_block.get("files") or {}
    universe_cfg = UniverseConfig(
        mode=(u_block.get("mode") or "starter").lower().strip(),
        include_etfs=bool(u_block.get("include_etfs", True)),
        include_leveraged_etfs=bool(u_block.get("include_leveraged_etfs", False)),
        source=(u_block.get("source") or "nasdaq_trader").lower().strip(),
        max_tickers_per_run=int(u_block.get("max_tickers_per_run", 5000)),
        cache_hours=int(u_block.get("cache_hours", 24)),
        recent_ipos_days=int(excl_block.get("recent_ipos_days", 30)),
        explicit_exclude=list(excl_block.get("explicit_tickers") or []),
        starter_lists=list(u_block.get("starter_lists") or []),
        file_all_us=files_block.get("all_us_symbols", "all_us_symbols.csv"),
        file_common_stocks=files_block.get("us_common_stocks", "us_common_stocks.csv"),
        file_etfs=files_block.get("us_etfs", "us_etfs.csv"),
        file_leveraged_etfs=files_block.get("us_leveraged_etfs", "us_leveraged_etfs.csv"),
        file_final=files_block.get("final_universe", "final_universe.csv"),
    )

    liquidity_cfg = LiquidityFilters(**settings_yaml["liquidity_filters"])
    trend_cfg = TrendFilters(**settings_yaml["trend_filters"])
    rs_cfg = RelativeStrengthFilters(**settings_yaml["relative_strength"])
    volume_cfg = VolumeFilters(**settings_yaml["volume_filters"])
    rr_cfg = RiskRewardFilters(**settings_yaml["risk_reward"])
    ext_cfg = ExtensionFilters(**settings_yaml["extension"])
    cont_cfg = ContinuationFilters(**settings_yaml["continuation"])

    scoring_block = settings_yaml["scoring"]
    scoring_cfg = ScoringConfig(
        weights=dict(scoring_block["weights"]),
        extension_penalty_max=int(scoring_block["extension_penalty_max"]),
        threshold_include=int(scoring_block["threshold_include"]),
        threshold_strong=int(scoring_block["threshold_strong"]),
        threshold_elite=int(scoring_block["threshold_elite"]),
    )

    reporting_block = settings_yaml["reporting"]
    reporting_cfg = ReportingConfig(
        output_dir=(PROJECT_ROOT / reporting_block["output_dir"]).resolve(),
        csv_filename_format=reporting_block["csv_filename_format"],
        watchlist_filename_format=reporting_block.get(
            "watchlist_filename_format", "{date}_watchlist.csv"
        ),
        summary_filename_format=reporting_block["summary_filename_format"],
        diagnostics_filename_format=reporting_block.get(
            "diagnostics_filename_format", "{date}_diagnostics.txt"
        ),
        rejected_filename_format=reporting_block.get(
            "rejected_filename_format", "{date}_rejected.csv"
        ),
        top_n_in_summary=int(reporting_block["top_n_in_summary"]),
        include_invalidated_in_csv=bool(reporting_block["include_invalidated_in_csv"]),
    )

    # --- Report mode (preset + overrides) ---
    rm_block = settings_yaml.get("report_mode") or {}
    active_mode = (rm_block.get("active") or "balanced").lower().strip()
    presets = rm_block.get("presets") or {}
    if active_mode not in presets:
        raise RuntimeError(
            f"report_mode.active={active_mode!r} but no matching preset in report_mode.presets. "
            f"Available: {list(presets.keys())}"
        )
    preset = presets[active_mode]

    # Thresholds: explicit values override the preset; null falls back to preset.
    th_block = settings_yaml.get("thresholds") or {}
    def _resolve_threshold(key: str, fallback: Any) -> Any:
        val = th_block.get(key)
        return fallback if val is None else val

    thresholds_cfg = Thresholds(
        main_report_score=int(_resolve_threshold(
            "main_report_score", preset["main_report_score"])),
        watchlist_score=int(_resolve_threshold(
            "watchlist_score", preset["watchlist_score"])),
        min_risk_reward=float(_resolve_threshold("min_risk_reward", 2.0)),
        max_distance_from_sma20=float(_resolve_threshold("max_distance_from_sma20", 8.0)),
        max_atr_extension=float(_resolve_threshold("max_atr_extension", 1.5)),
        min_relative_volume=float(_resolve_threshold("min_relative_volume", 1.5)),
    )

    report_mode_cfg = ReportMode(
        active=active_mode,
        main_report_score=thresholds_cfg.main_report_score,
        watchlist_score=thresholds_cfg.watchlist_score,
        label_low_confidence=bool(preset.get("label_low_confidence", False)),
    )

    # --- Liquidity V2 ---
    lv2 = settings_yaml.get("liquidity_v2") or {}
    liquidity_v2_cfg = LiquidityV2Config(
        min_price=float(lv2.get("min_price", 10.0)),
        low_price_volume_multiplier=float(lv2.get("low_price_volume_multiplier", 2.0)),
        min_avg_volume=int(lv2.get("min_avg_volume", 700_000)),
        preferred_avg_volume=int(lv2.get("preferred_avg_volume", 1_000_000)),
        min_avg_dollar_volume=float(lv2.get("min_avg_dollar_volume", 10_000_000)),
        preferred_avg_dollar_volume=float(lv2.get("preferred_avg_dollar_volume", 20_000_000)),
        min_rvol_for_signals=float(lv2.get("min_rvol_for_signals", 1.5)),
        strong_rvol=float(lv2.get("strong_rvol", 2.0)),
        exceptional_rvol=float(lv2.get("exceptional_rvol", 3.0)),
        min_current_dollar_volume=float(lv2.get("min_current_dollar_volume", 1_000_000)),
        max_spread_pct=float(lv2.get("max_spread_pct", 0.50)),
        warn_spread_pct=float(lv2.get("warn_spread_pct", 0.30)),
        apply_spread_filter=bool(lv2.get("apply_spread_filter", True)),
        min_market_cap=float(lv2.get("min_market_cap", 300_000_000)),
        warn_market_cap=float(lv2.get("warn_market_cap", 500_000_000)),
        low_float_threshold=float(lv2.get("low_float_threshold", 10_000_000)),
        score_weights=dict(lv2.get("score_weights") or {
            "price_quality": 10, "avg_volume": 15, "avg_dollar_volume": 20,
            "current_volume": 10, "current_dollar_volume": 10,
            "spread_quality": 10, "exchange_quality": 10,
            "market_cap_quality": 10, "missing_data_penalty": 5,
        }),
        min_liquidity_score=int(lv2.get("min_liquidity_score", 40)),
        warn_liquidity_score=int(lv2.get("warn_liquidity_score", 60)),
    )

    # 5. Validate scoring weights add up to 100 (loose check: allow extension_penalty out)
    weight_sum = sum(scoring_cfg.weights.values())
    if weight_sum != 100:
        # Not fatal but worth warning. We use print here because logging
        # isn't configured yet at this point in startup.
        print(
            f"[config] WARNING: scoring weights sum to {weight_sum}, not 100. "
            f"Final scores will still be normalized but check config/settings.yaml."
        )

    # 6. Active universe lists (starter mode)

    return Settings(
        provider=provider,
        _tiingo_api_key=os.getenv("TIINGO_API_KEY", "").strip(),
        _polygon_api_key=_load_polygon_api_key_for_settings(),
        _alpaca_api_key=os.getenv("ALPACA_API_KEY", "").strip(),
        _alpaca_secret_key=os.getenv("ALPACA_SECRET_KEY", "").strip(),
        _alpaca_base_url=os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        data=data_cfg,
        universe_cfg=universe_cfg,
        liquidity=liquidity_cfg,
        trend=trend_cfg,
        relative_strength=rs_cfg,
        volume=volume_cfg,
        risk_reward=rr_cfg,
        extension=ext_cfg,
        continuation=cont_cfg,
        scoring=scoring_cfg,
        reporting=reporting_cfg,
        report_mode=report_mode_cfg,
        thresholds=thresholds_cfg,
        liquidity_v2=liquidity_v2_cfg,
        universe_raw=universe_yaml,
        strategies_raw=strategies_yaml,
        active_universe_lists=universe_cfg.starter_lists,
    )


# =============================================================================
# Convenience: ensure required directories exist
# =============================================================================

def ensure_directories(settings: Settings) -> None:
    """Create cache, reports, and logs directories if they don't exist."""
    for d in (settings.data.cache_dir, settings.reporting.output_dir, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)
