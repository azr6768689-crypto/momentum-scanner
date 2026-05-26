"""Live + Alerts + Presets UI for Apex dashboard."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent


def _get_provider():
    from src.config import ensure_directories, load_settings
    from src.data import get_provider
    from src.polygon_key_store import apply_polygon_key_to_env

    apply_polygon_key_to_env()
    settings = load_settings()
    ensure_directories(settings)
    return get_provider(settings), settings.provider


@st.fragment(run_every=timedelta(seconds=int(os.getenv("APEX_LIVE_REFRESH_SEC", "60"))))
def _live_refresh_fragment(watchlist: list[str], daily_df: pd.DataFrame | None) -> None:
    if not st.session_state.get("apex_live_auto", True):
        return
    _render_live_panel(watchlist, daily_df, inside_fragment=True)


def _render_live_panel(
    watchlist: list[str],
    daily_df: pd.DataFrame | None,
    *,
    inside_fragment: bool = False,
) -> None:
    from src.apex_live.alerts import load_alerts
    from src.apex_live.live_engine import scan_live_watchlist
    from src.apex_live.session import is_us_market_open, session_label

    st.caption(f"מצב שוק: **{session_label()}** · רענון אוטומטי כל {os.getenv('APEX_LIVE_REFRESH_SEC', '60')} שנ׳")

    if _provider_label() == "demo":
        st.info("Live עם דמו — סימולציה תוך-יומית. Polygon = נתונים אמיתיים בזמן אמת.")

    try:
        provider, pname = _get_provider()
    except Exception as exc:
        st.error(f"לא ניתן לטעון ספק נתונים: {exc}")
        return

    with st.spinner(f"מרענן {len(watchlist)} מניות…"):
        snaps, new_events = scan_live_watchlist(
            watchlist,
            provider,
            daily_df,
            workers=int(os.getenv("APEX_LIVE_WORKERS", "6")),
        )

    if not snaps:
        st.warning("אין נתונים תוך-יומיים — בדוק מפתח Polygon או שעות מסחר.")
        return

    live_df = pd.DataFrame([s.to_row() for s in snaps])
    st.dataframe(live_df, use_container_width=True, height=400)

    if new_events:
        st.success(f"**{len(new_events)} התראות חדשות**")
        for ev in new_events[:15]:
            st.markdown(f"- `{ev.created_at}` **{ev.symbol}** — {ev.message}")

    recent = load_alerts(30)
    if recent:
        with st.expander("היסטוריית התראות"):
            for ev in recent:
                st.caption(f"{ev.created_at} · {ev.symbol}: {ev.message}")

    st.session_state["apex_live_last"] = live_df.to_dict(orient="records")
    if not inside_fragment:
        st.caption(f"ספק: {pname} · {len(snaps)} מניות")


def _provider_label() -> str:
    from src.polygon_key_store import resolve_polygon_api_key

    if resolve_polygon_api_key():
        return "polygon"
    return os.getenv("DATA_PROVIDER", "demo")


def render_live_tab(daily_df: pd.DataFrame) -> None:
    st.markdown("### ⚡ Live — Trade Ideas Layer")
    st.caption("מחיר, שינוי יום, RVOL תוך-יומי, VWAP, התראות אוטומטיות")

    top_n = st.slider("גודל Watchlist (מובילים מהדוח)", 5, 100, 40)
    if "סימבול" in daily_df.columns and "Apex Score" in daily_df.columns:
        default_list = (
            daily_df.sort_values("Apex Score", ascending=False)["סימבול"]
            .astype(str)
            .head(top_n)
            .tolist()
        )
    else:
        default_list = []

    custom = st.text_area(
        "Watchlist (פסיקים)",
        value=",".join(default_list),
        height=80,
    )
    watchlist = [s.strip().upper() for s in custom.replace("\n", ",").split(",") if s.strip()]

    c1, c2, c3 = st.columns(3)
    with c1:
        st.session_state["apex_live_auto"] = st.toggle("רענון אוטומטי", value=st.session_state.get("apex_live_auto", True))
    with c2:
        if st.button("רענן עכשיו", type="primary"):
            _render_live_panel(watchlist, daily_df)
    with c3:
        st.caption("Polygon minute/5min bars")

    if st.session_state.get("apex_live_auto"):
        if not st.session_state.get("apex_live_boot"):
            st.session_state["apex_live_boot"] = True
            _render_live_panel(watchlist, daily_df)
        _live_refresh_fragment(watchlist, daily_df)
    elif st.button("טען Live", type="secondary"):
        _render_live_panel(watchlist, daily_df)


def render_presets_tab(daily_df: pd.DataFrame) -> None:
    from src.apex_live.presets import list_presets, run_preset_on_report

    st.markdown("### 📋 סריקות מוכנות (Presets)")
    presets = list_presets()
    choice = st.selectbox(
        "אסטרטגיה",
        presets,
        format_func=lambda p: f"{p.name_he} — {p.description_he}",
    )
    if st.button("הרץ Preset על הדוח", type="primary"):
        result = run_preset_on_report(daily_df, choice.id)
        st.success(f"נמצאו {len(result)} מניות")
        st.dataframe(result.head(100), use_container_width=True)


def render_alerts_tab() -> None:
    from src.apex_live.alerts import load_alerts, load_rules, save_rules

    st.markdown("### 🔔 התראות")
    rules = load_rules()
    st.caption("כללי ברירת מחדל: RVOL≥2, עלייה יומית≥3%, מעל טריגר מהדוח היומי")

    for rule in rules:
        with st.expander(f"{rule.name} ({rule.kind})"):
            st.write(f"סף: {rule.threshold} · סימבול: {rule.symbol or 'הכל'}")
            rule.enabled = st.checkbox("פעיל", value=rule.enabled, key=f"rule_en_{rule.id}")

    if st.button("שמור כללים"):
        save_rules(rules)
        st.success("נשמר")

    events = load_alerts(50)
    if events:
        st.dataframe(
            pd.DataFrame([{"זמן": e.created_at, "מניה": e.symbol, "הודעה": e.message} for e in events]),
            use_container_width=True,
        )
    else:
        st.info("אין התראות עדיין — הפעל לשונית Live עם רענון אוטומטי.")
