"""
Scan depth presets — same universe and core scoring; differ in enrichment & backtest depth.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ScanProfile:
    id: str
    label_he: str
    summary_he: str
    reliability_he: str
    time_mac_cache_he: str
    time_mac_cold_he: str
    time_colab_cache_he: str
    time_colab_cold_he: str
    time_hf_cache_he: str
    time_hf_cold_he: str
    fast_parallel: bool
    skip_per_ticker_backtest: bool
    trim_bars: int | None
    intraday_top: int
    news_top: int
    skip_weekly_sparklines: bool
    output_suffix: str
    timeout_seconds: int
    a_plus_min_score: int
    watchlist_min_score: int
    early_min_score: int


PROFILES: dict[str, ScanProfile] = {
    "simple": ScanProfile(
        id="simple",
        label_he="פשוטה (מהירה)",
        summary_he="כל 2,114 המניות · דירוג מלא · בלי חדשות/שעתי",
        reliability_he=(
            "אמינות גבוהה לדירוג ולסינון: אותו מנוע דפוסים, מגמה, מוסדי ושוק. "
            "ללא Backtest היסטורי לכל מניה וללא חדשות Polygon — מתאים לסריקה יומית מהירה."
        ),
        time_mac_cache_he="כ־15–25 שניות",
        time_mac_cold_he="כ־15–25 דקות (פעם ראשונה / קאש פג)",
        time_colab_cache_he="כ־30–60 שניות",
        time_colab_cold_he="כ־20–40 דקות (פעם ראשונה ב-Drive)",
        time_hf_cache_he="כ־2–5 דקות",
        time_hf_cold_he="כ־5–12 דקות (ענן / demo)",
        fast_parallel=True,
        skip_per_ticker_backtest=True,
        trim_bars=252,
        intraday_top=0,
        news_top=0,
        skip_weekly_sparklines=True,
        output_suffix="us_simple",
        timeout_seconds=600,
        a_plus_min_score=85,
        watchlist_min_score=70,
        early_min_score=45,
    ),
    "medium": ScanProfile(
        id="medium",
        label_he="בינונית (מאוזנת)",
        summary_he="כל המניות · גרפים שעתיים ל-25 הראשונות · חדשות ל-40",
        reliability_he=(
            "אמינות גבוהה + העשרה: היסטוריית מחיר מלאה לדפוסים, חדשות וגרף שעתי "
            "למניות המובילות בלבד. ללא Backtest כבד לכל מניה — איזון זמן/עומק."
        ),
        time_mac_cache_he="כ־45–90 שניות",
        time_mac_cold_he="כ־18–30 דקות",
        time_colab_cache_he="כ־1.5–3 דקות",
        time_colab_cold_he="כ־25–45 דקות",
        time_hf_cache_he="כ־8–15 דקות",
        time_hf_cold_he="כ־25–40 דקות (פעם ראשונה בענן)",
        fast_parallel=False,
        skip_per_ticker_backtest=True,
        trim_bars=None,
        intraday_top=25,
        news_top=40,
        skip_weekly_sparklines=False,
        output_suffix="us_medium",
        timeout_seconds=900,
        a_plus_min_score=88,
        watchlist_min_score=73,
        early_min_score=48,
    ),
    "full": ScanProfile(
        id="full",
        label_he="מקיפה (מלאה)",
        summary_he="כל המניות · Backtest לכל מניה · שעתי 50 · חדשות 100",
        reliability_he=(
            "העומק המקסימלי: Backtest היסטורי מקומי לכל מניה, אגרגציית אסטרטגיות, "
            "חדשות וגרפים שעתיים לטופ. הכי אמין לניתוח לפני החלטה — הכי ארוך."
        ),
        time_mac_cache_he="כ־1.5–3 דקות",
        time_mac_cold_he="כ־20–40 דקות",
        time_colab_cache_he="כ־3–6 דקות",
        time_colab_cold_he="כ־35–70 דקות",
        time_hf_cache_he="כ־12–25 דקות",
        time_hf_cold_he="כ־40–75 דקות (פעם ראשונה בענן)",
        fast_parallel=False,
        skip_per_ticker_backtest=False,
        trim_bars=None,
        intraday_top=50,
        news_top=100,
        skip_weekly_sparklines=False,
        output_suffix="us_full",
        timeout_seconds=2400,
        a_plus_min_score=90,
        watchlist_min_score=76,
        early_min_score=50,
    ),
}

DEFAULT_PROFILE_ID = "simple"


def list_profiles() -> list[ScanProfile]:
    return [PROFILES[k] for k in ("simple", "medium", "full")]


def get_profile(profile_id: str | None) -> ScanProfile:
    key = (profile_id or os.getenv("SCAN_PROFILE", DEFAULT_PROFILE_ID)).strip().lower()
    if key not in PROFILES:
        raise ValueError(f"Unknown scan profile '{profile_id}'. Choose: simple, medium, full.")
    return PROFILES[key]


def apply_profile_to_env(profile: ScanProfile) -> None:
    """Set process env vars consumed by the scanner and report builder."""
    os.environ["SCAN_PROFILE"] = profile.id
    os.environ["SCAN_FAST"] = "1" if profile.fast_parallel else "0"
    os.environ["SCAN_FAST_CHARTS"] = "1" if profile.id == "simple" else "0"
    os.environ["SCAN_SKIP_BACKTEST"] = "1" if profile.skip_per_ticker_backtest else "0"
    os.environ["SCAN_SKIP_WEEKLY_SPARKLINES"] = "1" if profile.skip_weekly_sparklines else "0"
    if profile.trim_bars is not None:
        os.environ["SCAN_TRIM_BARS"] = str(profile.trim_bars)
    else:
        os.environ.pop("SCAN_TRIM_BARS", None)
    os.environ["SCAN_A_PLUS_MIN_SCORE"] = str(profile.a_plus_min_score)
    os.environ["SCAN_WATCHLIST_MIN_SCORE"] = str(profile.watchlist_min_score)
    os.environ["SCAN_EARLY_MIN_SCORE"] = str(profile.early_min_score)


def profile_help_markdown(profile: ScanProfile, *, cloud: bool = False) -> str:
    where = "ענן (קישור מהמייל)" if cloud else "Mac מקומי"
    cache_key = "time_hf_cache_he" if cloud else "time_mac_cache_he"
    cold_key = "time_hf_cold_he" if cloud else "time_mac_cold_he"
    return (
        f"**{profile.label_he}** — {profile.summary_he}\n\n"
        f"{profile.reliability_he}\n\n"
        f"**זמן משוער ({where}, קאש חם):** {getattr(profile, cache_key)}  \n"
        f"**זמן משוער ({where}, פעם ראשונה / ללא קאש):** {getattr(profile, cold_key)}  \n"
        f"**זמן משוער (Colab + Drive, קאש חם):** {profile.time_colab_cache_he}  \n"
        f"**זמן משוער (Colab, ללא קאש):** {profile.time_colab_cold_he}"
    )


def profile_time_table_markdown(*, cloud: bool = False) -> str:
    """Compact ETA table for all three scan levels."""
    rows = []
    for p in list_profiles():
        if cloud:
            rows.append(
                f"| {p.label_he} | {p.time_hf_cache_he} | {p.time_hf_cold_he} |"
            )
        else:
            rows.append(
                f"| {p.label_he} | {p.time_mac_cache_he} | {p.time_mac_cold_he} |"
            )
    header = (
        "| רמה | אחרי קאש (מהיר) | פעם ראשונה / ללא קאש |\n"
        "|------|------------------|------------------------|\n"
    )
    return header + "\n".join(rows)
