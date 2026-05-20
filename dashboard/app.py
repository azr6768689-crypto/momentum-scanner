"""
Streamlit dashboard for the Momentum Decision-Support System.

Loads the latest CSV report from data/reports/ and presents an interactive
view with filters, sorting, and per-setup details.

Usage (from project root):
    streamlit run dashboard/app.py

This dashboard does NOT:
- Place trades
- Connect to brokers
- Send alerts
- Modify the underlying data

It is read-only — a window into the daily report.
"""

from __future__ import annotations

import hmac
import os
import subprocess
import sys
import re
import json
import html
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import pandas as pd
from pandas.errors import EmptyDataError
import altair as alt
import streamlit as st
import streamlit.components.v1 as components

# Ensure project root is on the import path (so config loader works)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.env_secrets import clean_env_secret
from src.polygon_key_store import (
    clear_polygon_api_key_file,
    polygon_key_tail,
    resolve_polygon_api_key,
    save_polygon_api_key,
)
from src.polygon_preflight import validate_polygon_api_key
from src.report_compare import attach_rank_delta
from src.report_paths import is_official_report_csv

# Path constants
REPORTS_DIR = ROOT / "data" / "reports"

# Cloud scan parallelism (Render Free: use 2 in render.yaml to avoid OOM).
def _cloud_scan_workers() -> int:
    raw = os.getenv("SCAN_WORKERS", "6").strip()
    try:
        return max(1, min(int(raw), 12))
    except ValueError:
        return 6


CLOUD_SCAN_WORKERS = _cloud_scan_workers()

BRAND_HE = "סורק הזהב"
BRAND_EN = "Golden Scanner"
LOGO_MARK = "GS"
CLOUD_APP_URL = "https://azr6768689-momentum-scanner.hf.space"
CLOUD_SPACE_PAGE_URL = "https://huggingface.co/spaces/azr6768689/momentum-scanner"
# Render sets RENDER_EXTERNAL_URL automatically (e.g. https://momentum-scanner-bbhl.onrender.com).


def _public_app_url() -> str:
    """Shareable app URL — Render/HF aware (not a broken default hf.space on Render)."""
    explicit = os.getenv("PUBLIC_APP_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    render_url = os.getenv("RENDER_EXTERNAL_URL", "").strip()
    if render_url:
        return render_url.rstrip("/")
    if os.getenv("RENDER", "").strip().lower() == "true":
        svc = os.getenv("RENDER_SERVICE_NAME", "momentum-scanner").strip()
        if svc:
            return f"https://{svc}.onrender.com"
    return CLOUD_APP_URL.rstrip("/")


def _is_cloud_space() -> bool:
    """True on Hugging Face Spaces or Render Web Services.

    Both need parallel scan workers, detached background scans (so Streamlit stays
    responsive), and the same timeout / Polygon messaging paths.
    """
    return bool(
        os.getenv("SPACE_ID")
        or os.getenv("SPACE_REPO_NAME")
        or os.getenv("STREAMLIT_SHARING_MODE")
        or (os.getenv("RENDER", "").strip().lower() == "true")
    )


def _resolve_polygon_api_key() -> str:
    return resolve_polygon_api_key()


def _preflight_polygon_key() -> tuple[bool, str]:
    return validate_polygon_api_key()


def _cloud_scan_limit(profile_id: str) -> int | None:
    """No symbol cap on cloud — full universe scan on server."""
    _ = profile_id
    return None

# Status color palette (consistent across CSS + badges)
STATUS_COLORS = {
    "Trigger":           "#16a34a",   # green
    "Watch":             "#eab308",   # yellow
    "Wait for pullback": "#06b6d4",   # cyan
    "Ignore":            "#6b7280",   # gray
    "Invalidated":       "#dc2626",   # red
}

BAND_COLORS = {
    "elite":       "#16a34a",
    "very_strong": "#eab308",
    "watch_only":  "#94a3b8",
    "excluded":    "#475569",
}

BAND_LABELS = {
    "elite":       "ELITE (90+)",
    "very_strong": "VERY STRONG (85-89)",
    "watch_only":  "WATCH ONLY (75-84)",
    "excluded":    "EXCLUDED (<75)",
}


# =============================================================================
# Page config + global CSS
# =============================================================================

st.set_page_config(
    page_title=f"{BRAND_EN} | {BRAND_HE}",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _rerun_app() -> None:
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


def _render_sidebar_brand() -> None:
    st.markdown(
        f"""
        <div class="sidebar-brand">
            <div class="sidebar-brand-top">
                <div>
                    <div class="sidebar-brand-title">{html.escape(BRAND_HE)}</div>
                    <div class="sidebar-brand-sub">{html.escape(BRAND_EN)} · US Equities</div>
                </div>
                <div class="sidebar-brand-logo gold-logo-mark">{LOGO_MARK}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_sidebar_section(title: str) -> None:
    st.markdown(f'<div class="sidebar-section-title">{html.escape(title)}</div>', unsafe_allow_html=True)


GOOGLE_FINANCE_AI_URL = "https://www.google.com/finance/beta/"
TRADINGVIEW_COPILOT_EXTENSION_URL = (
    "https://chromewebstore.google.com/detail/tradingview-remix-ai-char/"
    "fchmejnoncmdhlebgdgifdnehoibalnd"
)


def _google_finance_url(symbol: str = "") -> str:
    sym = str(symbol or "").upper().strip()
    if sym:
        return f"https://www.google.com/finance/quote/{quote(sym)}:NASDAQ"
    return GOOGLE_FINANCE_AI_URL


def _tradingview_copilot_chart_url(symbol: str = "") -> str:
    sym = str(symbol or "").upper().strip()
    if sym:
        return _tradingview_url(sym)
    return "https://www.tradingview.com/chart/"


def _scan_context_ticker() -> str:
    for key in ("selected_ticker", "detail_ticker", "last_ticker"):
        val = st.session_state.get(key)
        if val:
            return str(val).upper().strip()
    raw = str(st.session_state.get("pro_table_ticker_filter", "") or "").strip().upper()
    if raw:
        return raw.split(",")[0].strip()
    qp = getattr(st, "query_params", None)
    if qp is not None:
        t = qp.get("ticker") or qp.get("symbol")
        if isinstance(t, list):
            t = t[0] if t else ""
        if t:
            return str(t).upper().strip()
    return ""


def _finviz_url(symbol: str = "") -> str:
    sym = str(symbol or "").upper().strip()
    if sym:
        return f"https://finviz.com/quote.ashx?t={quote(sym)}"
    return "https://finviz.com/"


def _render_scan_assistant_links() -> None:
    """External research: Google Finance, TradingView, Finviz."""
    ticker = _scan_context_ticker()
    ticker_note = (
        f'<div class="advisory-ticker">טיקר נוכחי: <strong>{html.escape(ticker)}</strong></div>'
        if ticker
        else '<div class="advisory-ticker">בחר מניה בטבלה או הזן סימבול בסינון</div>'
    )
    gf = html.escape(_google_finance_url(ticker))
    tv = html.escape(_tradingview_copilot_chart_url(ticker))
    fv = html.escape(_finviz_url(ticker))
    st.markdown(
        f"""
        <div class="advisory-hub">
            {ticker_note}
            <div class="advisory-tiles">
                <a class="advisory-tile advisory-tile-gf" href="{gf}" target="_blank" rel="noopener">
                    <span class="advisory-tile-kicker">AI · חדשות</span>
                    <span class="advisory-tile-title">Google Finance</span>
                    <span class="advisory-tile-sub">Gemini · Deep Search</span>
                </a>
                <a class="advisory-tile advisory-tile-tv" href="{tv}" target="_blank" rel="noopener">
                    <span class="advisory-tile-kicker">גרפים</span>
                    <span class="advisory-tile-title">TradingView</span>
                    <span class="advisory-tile-sub">גרף + Copilot AI</span>
                </a>
                <a class="advisory-tile advisory-tile-fv" href="{fv}" target="_blank" rel="noopener">
                    <span class="advisory-tile-kicker">מפת חום</span>
                    <span class="advisory-tile-title">Finviz</span>
                    <span class="advisory-tile-sub">סקטור · ווליום · טכני</span>
                </a>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("הקישורים נפתחים בטאב חדש · מומלץ לצמד לניתוח מהסורק")


def _scan_panel_enabled() -> bool:
    if _is_cloud_space():
        return True
    return os.getenv("ENABLE_DASHBOARD_SCAN_BUTTON", "true").lower() not in {"0", "false", "no"}


def _deploy_build_label() -> str:
    version_path = ROOT / "DEPLOY_VERSION.txt"
    if version_path.is_file():
        return version_path.read_text(encoding="utf-8").strip()
    return "local-dev"


def _init_scan_ui_state() -> None:
    """Open scan panel when there is no report yet (cloud)."""
    if _is_cloud_space() and not _discover_report_paths():
        st.session_state.setdefault("scan_panel_open", True)
    else:
        st.session_state.setdefault("scan_panel_open", False)


def _render_polygon_key_setup() -> None:
    """Let user paste a working Polygon key without using Render dashboard."""
    ok_pf, pf_msg = _preflight_polygon_key_cached()
    if ok_pf:
        st.session_state.pop("polygon_scan_error", None)
        tail = polygon_key_tail()
        st.success(f"מפתח Polygon תקין · …{tail}")
        return

    st.session_state["polygon_scan_error"] = pf_msg
    st.error(pf_msg)
    stored = resolve_polygon_api_key()
    if stored:
        st.caption(f"מפתח שמור כרגע: …{polygon_key_tail(stored)} ({len(stored)} תווים)")
    st.info(
        "1. היכנס ל-[polygon.io/dashboard/api-keys](https://polygon.io/dashboard/api-keys)\n"
        "2. לחץ **+ New Key** → שם כלשהו → **Copy**\n"
        "3. הדבק כאן **רק** את המפתח (30+ תווים, בלי מרכאות)\n"
        "4. **לא** Publishable / לא GitHub / לא HF"
    )
    new_key = st.text_input("הדבק מפתח Polygon", type="password", key="polygon_key_paste")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("שמור מפתח והפעל סריקה", type="primary", key="polygon_key_save_btn"):
            try:
                save_polygon_api_key(new_key)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.session_state.pop("_polygon_preflight_cache", None)
                st.session_state.pop("polygon_scan_error", None)
                st.session_state.pop("auto_scan_on_entry_done", None)
                _rerun_app()
    with c2:
        if st.button("מחק מפתח שמור", key="polygon_key_clear_btn"):
            clear_polygon_api_key_file()
            st.session_state.pop("_polygon_preflight_cache", None)
            st.session_state.pop("polygon_scan_error", None)
            _rerun_app()


def _default_scan_profile_id() -> str:
    from src.scan_profiles import list_profiles

    profiles = list_profiles()
    profile_ids = [p.id for p in profiles]
    default_profile = os.getenv("SCAN_PROFILE", "simple")
    if default_profile not in profile_ids:
        default_profile = "simple"
    return default_profile


def _handle_cloud_scan_lifecycle() -> None:
    """Auto-scan, polling, and report reload — always active (not tied to panel visibility)."""
    if not _is_cloud_space():
        return
    ok_pf, pf_msg = _preflight_polygon_key_cached()
    if not ok_pf:
        st.session_state["polygon_scan_error"] = pf_msg
    else:
        st.session_state.pop("polygon_scan_error", None)
        _maybe_auto_scan_on_entry(_default_scan_profile_id())
    _maybe_reload_after_scan_ok()
    try:
        from src.cloud_scan_job import get_status
    except Exception:
        return
    if get_status().get("state") == "running" and hasattr(st, "autorefresh"):
        st.autorefresh(interval=10_000, key="cloud_scan_global_poll")


def _scan_progress_details() -> tuple[int, str, str]:
    """Return (percent 0–100, state, short message)."""
    try:
        from src.cloud_scan_job import get_scan_progress, get_status

        job = get_status()
        state = str(job.get("state", "idle"))
        if state == "idle":
            return 0, state, ""
        if state == "ok":
            return 100, state, str(job.get("message", "הושלם"))
        prog = job.get("progress") or get_scan_progress()
        pct = max(0, min(100, int(prog.get("percent", 0))))
        msg = str(prog.get("message") or job.get("message") or "סריקה…")
        return pct, state, msg
    except Exception:
        return 0, "idle", ""


def _scan_rail_percent() -> int:
    pct, _, _ = _scan_progress_details()
    return pct


def _render_scan_progress_panel() -> None:
    """Vertical progress rail + st.progress — always at top of sidebar."""
    st.caption(f"גרסה: {_deploy_build_label()}")
    pct, state, msg = _scan_progress_details()
    fill_h = pct if pct > 0 else 0
    status_line = "ממתין לסריקה"
    if state == "running":
        status_line = f"סריקה {pct}%"
    elif state == "ok":
        status_line = "הסריקה הושלמה ✓"
    elif state == "error":
        status_line = "שגיאה בסריקה"

    rail_col, info_col = st.columns([0.14, 0.86], gap="small")
    with rail_col:
        st.markdown(
            f"""
            <div class="sidebar-scan-rail">
                <div class="sidebar-scan-rail-fill" style="height:{fill_h}%;"></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with info_col:
        st.markdown(f"**{html.escape(status_line)}**")
        if msg and state == "running":
            st.caption(html.escape(msg[:72]))

    st.progress(min(1.0, max(0.0, pct / 100.0)))
    if state == "error" and msg:
        st.error(msg[:200])
    st.divider()


def _render_scan_sidebar_tab() -> None:
    """Scan toggle — always at the top of the sidebar (no CSS hacks)."""
    if not _scan_panel_enabled():
        return
    build = _deploy_build_label()
    is_open = st.session_state.get("scan_panel_open", False)
    label = f"✕ סגור · {build}" if is_open else f"🔎 סריקה · {build}"
    if st.button(label, type="primary", use_container_width=True, key="scan_sidebar_tab_btn"):
        st.session_state["scan_panel_open"] = not is_open
        _rerun_app()


def _render_cloud_access_panel() -> None:
    """Two share links only — Render + Hugging Face."""
    render_url = (
        os.getenv("RENDER_EXTERNAL_URL", "").strip()
        or "https://momentum-scanner-bbhl.onrender.com"
    ).rstrip("/")
    hf_url = (os.getenv("ALTERNATE_APP_URL", "") or CLOUD_APP_URL).strip().rstrip("/")
    st.link_button("Render", render_url, use_container_width=True)
    st.link_button("Hugging Face", hf_url, use_container_width=True)


def _rank_delta_badge_html(delta: str) -> str:
    d = str(delta or "—")
    css = "rank-delta-flat"
    if d == "חדש":
        css = "rank-delta-new"
    elif d.startswith("↑"):
        css = "rank-delta-up"
    elif d.startswith("↓"):
        css = "rank-delta-down"
    return f'<span class="rank-delta-badge {css}">{html.escape(d)}</span>'


def _build_ticker_advice_lines(row: pd.Series) -> list[str]:
    """Hebrew advisory bullets derived from the report row (DF)."""
    lines: list[str] = []
    level = str(row.get("רמה", "") or "")
    prob = int(row.get("הסתברות %", 0) or 0)
    pattern = str(row.get("דפוס", "") or "")
    breakout = str(row.get("מצב פריצה", "") or "")
    market_ok = str(row.get("אישור שוק ללונג", "") or "")
    rvol = float(row.get("ווליום יחסי", 0) or 0)
    rank_delta = str(row.get("שינוי דירוג", "") or "—")
    entry = row.get("נקודת כניסה")
    stop = row.get("סטופ / ביטול", row.get("הערת סיכון", ""))

    if level == "A+ Setup":
        lines.append("מועמדת A+ — עומדת בכל שערי האיכות. התמקד באישור פריצה מעל נקודת הכניסה עם ווליום.")
    elif level == "Watchlist":
        lines.append("Watchlist — קרובה ל-setup. המתן טריגר ברור (פריצה + ווליום) לפני כניסה.")
    elif level == "Early Momentum":
        lines.append("מומנטום מוקדם — פוטנציאל אבל עדיין לא A+. מעקב הדוק, גודל פוזיציה קטן יותר.")
    else:
        lines.append("לא ברמת כניסה כרגע לפי הסורק — עדיף לרשימת מעקב בלבד.")

    if prob >= 90:
        lines.append(f"ציון הסתברות גבוה ({prob}/100) — איכות סט-אפ חזקה ביחס למניות אחרות בדוח.")
    elif prob >= 75:
        lines.append(f"ציון בינוני-גבוה ({prob}/100) — בדוק שאין התנגשות עם מגמת שוק חלשה.")
    else:
        lines.append(f"ציון נמוך יחסית ({prob}/100) — זהירות, אל תסמוך על דירוג בלבד.")

    if pattern and pattern != "אין דפוס פריצה איכותי כרגע":
        lines.append(f"דפוס מוביל: {pattern}.")
    if breakout:
        lines.append(f"פריצה: {breakout}.")
    if market_ok == "תומך":
        lines.append("שוק תומך ללונג — רוח בעובר.")
    elif market_ok and market_ok != "לא נבדק":
        lines.append(f"שוק: {market_ok} — שקול גודל פוזיציה.")
    if rvol >= 1.5:
        lines.append(f"ווליום יחסי חזק ({rvol:.1f}x) — מאשר עניין.")
    elif rvol < 0.9:
        lines.append(f"ווליום חלש ({rvol:.1f}x) — חסר אישור קונים.")

    if rank_delta.startswith("↑"):
        lines.append(f"עלתה בדירוג לעומת אתמול ({rank_delta}) — המומנטום מתחזק ביחס לדוח הקודם.")
    elif rank_delta.startswith("↓"):
        lines.append(f"ירדה בדירוג ({rank_delta}) — בדוק אם יש משיכת רווחים או חולשה יחסית.")
    elif rank_delta == "חדש":
        lines.append("חדשה בטופ הדירוג היום — לא הייתה באותו דוח אתמול.")

    if pd.notna(entry):
        try:
            lines.append(f"טריגר מוצע: מעל ${float(entry):.2f}.")
        except (TypeError, ValueError):
            pass
    if stop and str(stop).strip():
        lines.append(f"ניהול סיכון: {str(stop).strip()[:120]}")

    lines.append("זה יעוץ מבוסס דאטה מהסורק — לא המלצת קנייה/מכירה.")
    return lines


def _render_ticker_advice_card(row: pd.Series) -> None:
    ticker = str(row.get("סימבול", "")).upper()
    level = str(row.get("רמה", ""))
    prob = int(row.get("הסתברות %", 0) or 0)
    rank = row.get("דירוג", "—")
    delta = str(row.get("שינוי דירוג", "—"))
    bullets = "".join(f"<li>{html.escape(line)}</li>" for line in _build_ticker_advice_lines(row))
    st.markdown(
        f"""
        <div class="ticker-advice-card">
            <div class="ticker-advice-title">{html.escape(ticker)} · {html.escape(level)} · {prob}/100</div>
            <div class="ticker-advice-meta">
                דירוג היום #{html.escape(str(rank))} · שינוי מאתמול: {_rank_delta_badge_html(delta)}
            </div>
            <ul class="ticker-advice-list">{bullets}</ul>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_decision_support_panel(df: pd.DataFrame, *, prev_report_date: str = "") -> None:
    with st.expander("💡 יעוץ לפי מניה", expanded=True):
        if df.empty or "סימבול" not in df.columns:
            st.info("אין דאטה ליעוץ — טען דוח תחילה.")
            return
        symbols = df["סימבול"].astype(str).tolist()
        hint = _scan_context_ticker()
        default_idx = symbols.index(hint) if hint in symbols else 0
        pick = st.selectbox(
            "בחר מניה",
            options=symbols,
            index=default_idx,
            key="advice_ticker_pick",
        )
        st.session_state["selected_ticker"] = pick.upper()
        st.session_state["detail_ticker"] = pick.upper()
        row = df[df["סימבול"].astype(str) == pick].iloc[0]
        if prev_report_date:
            st.caption(f"השוואת דירוג מול דוח: {prev_report_date}")
        _render_ticker_advice_card(row)
        st.divider()
        st.markdown("**קישורים חיצוניים**")
        _render_scan_assistant_links()


def _render_sidebar_file_card(name: str, size_kb: float, generated: str) -> None:
    st.markdown(
        f"""
        <div class="sidebar-card">
            <div class="label">קובץ דוח</div>
            <div class="value">{html.escape(name)}</div>
            <div class="label" style="margin-top:8px;">גודל</div>
            <div class="value">{size_kb:.1f} KB</div>
            <div class="label" style="margin-top:8px;">נוצר</div>
            <div class="value">{html.escape(generated)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _require_dashboard_password() -> None:
    password = clean_env_secret(os.getenv("DASHBOARD_PASSWORD", ""))
    if not password or st.session_state.get("dashboard_authenticated"):
        return

    st.markdown(
        f"""
        <div class="hero-card" style="max-width: 520px; margin: 4rem auto 1rem;">
            <div class="hero-title" style="font-size: 2rem;">{html.escape(BRAND_HE)}</div>
            <div class="hero-subtitle">{html.escape(BRAND_EN)} · כניסה מאובטחת</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("המערכת מוגנת בסיסמה כי היא מכילה כלי סריקה פרטי ונתוני API.")
    st.info(
        "הסיסמה היא **DASHBOARD_PASSWORD** ב-Render → Environment. "
        "אחרי שינוי — Save → חכה ל-restart → נסה שוב **בלי רווחים**."
    )
    entered = st.text_input("סיסמה", type="password")
    if st.button("כניסה", use_container_width=True, type="primary"):
        if not entered.strip():
            st.warning("הזן סיסמה.")
        elif hmac.compare_digest(
            entered.strip().encode("utf-8"),
            password.encode("utf-8"),
        ):
            st.session_state["dashboard_authenticated"] = True
            st.session_state.pop("auto_scan_on_entry_done", None)
            st.session_state.pop("_polygon_preflight_cache", None)
            _rerun_app()
        else:
            st.error(
                "סיסמה לא נכונה. Render → Environment → **DASHBOARD_PASSWORD** — "
                "הדבק סיסמה חדשה (בלי מרכאות), Save, חכה דקה, נסה שוב."
            )
    st.stop()


st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700;800&family=Playfair+Display:wght@600;700&display=swap');
    header[data-testid="stHeader"],
    [data-testid="stToolbar"],
    [data-testid="stDecoration"] {
        display: none !important;
        height: 0 !important;
        min-height: 0 !important;
    }
    footer, #MainMenu { visibility: hidden; }
    section[data-testid="stSidebar"] {
        transform: translateX(0) !important;
        visibility: visible !important;
        min-width: 19rem !important;
    }
    [data-testid="stSidebarCollapsedControl"] {
        display: none !important;
    }
    .sidebar-scan-rail {
        width: 100%;
        min-height: 130px;
        background: rgba(37, 99, 235, 0.16);
        border-radius: 8px;
        position: relative;
        overflow: hidden;
        border: 1px solid rgba(96, 165, 250, 0.45);
    }
    .sidebar-scan-rail-fill {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        background: linear-gradient(to top, #06b6d4 0%, #2563eb 100%);
        transition: height 0.35s ease;
        box-shadow: 0 0 12px rgba(6, 182, 212, 0.45);
    }
    .block-container { padding-top: 0.75rem !important; }
    .stApp {
        background:
            radial-gradient(circle at 8% 5%, rgba(56, 189, 248, 0.35), transparent 26%),
            radial-gradient(circle at 92% 2%, rgba(14, 165, 233, 0.12), transparent 28%),
            radial-gradient(circle at 50% 35%, rgba(34, 197, 94, 0.15), transparent 24%),
            linear-gradient(160deg, #060d18 0%, #0c1a2e 45%, #0f2438 100%);
        color: #f8fafc;
    }
    .block-container {
        padding-top: 1.25rem;
        padding-left: 1rem;
        padding-right: 1rem;
    }
    .stApp::before {
        content: "";
        position: fixed;
        inset: 0;
        pointer-events: none;
        background-image:
            linear-gradient(rgba(255,255,255,0.035) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255,255,255,0.035) 1px, transparent 1px);
        background-size: 46px 46px;
        mask-image: linear-gradient(to bottom, rgba(0,0,0,.75), transparent 72%);
        z-index: 0;
    }
    [data-testid="stDataFrame"] {
        border-radius: 16px;
        border: 1px solid rgba(59, 130, 246, 0.35);
        box-shadow: 0 18px 42px rgba(2, 6, 23, 0.45);
        overflow: hidden;
        font-size: 0.78rem;
    }
    [data-testid="stDataFrame"] * {
        font-size: 0.78rem !important;
    }
    [data-testid="stMetric"] {
        background:
            radial-gradient(circle at top right, rgba(34,211,238,0.18), transparent 34%),
            linear-gradient(145deg, rgba(15, 23, 42, 0.78), rgba(30, 41, 59, 0.68));
        border: 1px solid rgba(125, 211, 252, 0.34);
        border-radius: 18px;
        padding: 12px;
        box-shadow: 0 18px 42px rgba(2, 6, 23, 0.28);
        backdrop-filter: blur(18px);
    }
    h1, h2, h3, h4, h5, h6,
    [data-testid="stMarkdownContainer"] h1,
    [data-testid="stMarkdownContainer"] h2,
    [data-testid="stMarkdownContainer"] h3,
    [data-testid="stMarkdownContainer"] h4 {
        color: #f8fafc !important;
        text-shadow: 0 2px 12px rgba(0,0,0,0.42);
    }
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stCaptionContainer"],
    [data-testid="stWidgetLabel"],
    label,
    .st-emotion-cache-ue6h4q,
    .st-emotion-cache-1vbkxwb {
        color: #e2e8f0 !important;
    }
    [data-testid="stMetricLabel"],
    [data-testid="stMetricLabel"] * {
        color: #bfdbfe !important;
        font-weight: 700 !important;
    }
    [data-testid="stMetricValue"],
    [data-testid="stMetricValue"] * {
        color: #ffffff !important;
        font-weight: 900 !important;
    }
    [data-testid="stSidebar"] {
        background:
            radial-gradient(circle at 0% 0%, rgba(56, 189, 248, 0.22), transparent 42%),
            radial-gradient(circle at 100% 8%, rgba(168, 85, 247, 0.20), transparent 38%),
            linear-gradient(180deg, #0b1224 0%, #111b33 48%, #0f172a 100%) !important;
        border-right: 1px solid rgba(96, 165, 250, 0.28);
        box-shadow: 12px 0 40px rgba(2, 6, 23, 0.45);
    }
    [data-testid="stSidebar"] > div:first-child {
        background: transparent !important;
    }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] li,
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"],
    [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] .st-emotion-cache-ue6h4q {
        color: #dbeafe !important;
    }
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h1,
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h2,
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3 {
        color: #f8fafc !important;
        letter-spacing: -0.02em;
    }
    [data-testid="stSidebar"] hr {
        border-color: rgba(96, 165, 250, 0.22) !important;
        margin: 0.85rem 0 !important;
    }
    .sidebar-brand,
    .hero-card,
    .metric-card,
    .sidebar-card,
    .scanner-top {
        pointer-events: none;
        user-select: none;
    }
    .sidebar-brand {
        padding: 14px 14px 12px;
        margin: 0 0 10px 0;
        border-radius: 18px;
        border: 1px solid rgba(96, 165, 250, 0.35);
        background:
            radial-gradient(circle at 88% 0%, rgba(244, 114, 182, 0.28), transparent 36%),
            radial-gradient(circle at 8% 10%, rgba(34, 211, 238, 0.24), transparent 34%),
            linear-gradient(145deg, rgba(30, 64, 175, 0.72), rgba(15, 23, 42, 0.88));
        box-shadow: 0 16px 36px rgba(2, 6, 23, 0.35);
        direction: rtl;
    }
    .sidebar-brand-top {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        margin-bottom: 8px;
    }
    .gold-logo-mark {
        font-family: 'Cinzel', 'Playfair Display', Georgia, serif;
        font-weight: 800;
        letter-spacing: 0.08em;
        color: #1c1408;
        background: linear-gradient(145deg, #fef3c7 0%, #d4af37 40%, #b8860b 75%, #fffbeb 100%) !important;
        border: 1px solid rgba(254, 243, 199, 0.7);
        box-shadow: 0 0 26px rgba(212, 175, 55, 0.42), inset 0 1px 0 rgba(255, 255, 255, 0.35);
        text-shadow: 0 1px 0 rgba(255, 255, 255, 0.3);
    }
    .sidebar-brand-logo {
        width: 42px;
        height: 42px;
        border-radius: 14px;
        display: grid;
        place-items: center;
        font-size: 0.72rem;
    }
    .sidebar-brand-title {
        font-family: 'Cinzel', 'Playfair Display', Georgia, serif;
        color: #fef3c7;
        font-size: 1.08rem;
        font-weight: 800;
        line-height: 1.2;
        letter-spacing: 0.02em;
    }
    .sidebar-brand-sub {
        color: #bfdbfe;
        font-size: 0.76rem;
        line-height: 1.35;
    }
    .sidebar-pill {
        display: inline-block;
        padding: 3px 9px;
        border-radius: 999px;
        font-size: 0.68rem;
        font-weight: 800;
        color: #ecfeff;
        background: rgba(34, 211, 238, 0.18);
        border: 1px solid rgba(34, 211, 238, 0.35);
    }
    .sidebar-section-title {
        color: #93c5fd;
        font-size: 0.72rem;
        font-weight: 800;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        margin: 2px 0 10px;
        direction: rtl;
    }
    .sidebar-card {
        padding: 12px 13px;
        border-radius: 16px;
        border: 1px solid rgba(96, 165, 250, 0.24);
        background: rgba(15, 23, 42, 0.72);
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05);
        margin-bottom: 10px;
        direction: rtl;
    }
    .sidebar-card .label {
        color: #94a3b8;
        font-size: 0.68rem;
        font-weight: 700;
        margin-bottom: 3px;
    }
    .sidebar-card .value {
        color: #f8fafc;
        font-size: 0.86rem;
        font-weight: 700;
        line-height: 1.35;
        overflow-wrap: anywhere;
        word-break: break-word;
    }
    .sidebar-profile-chip {
        display: inline-block;
        margin-top: 6px;
        padding: 4px 10px;
        border-radius: 999px;
        font-size: 0.72rem;
        font-weight: 800;
        color: #f8fafc;
        background: linear-gradient(135deg, rgba(37, 99, 235, 0.55), rgba(6, 182, 212, 0.45));
        border: 1px solid rgba(125, 211, 252, 0.35);
    }
    [data-testid="stSidebar"] div.stButton > button[kind="primary"],
    [data-testid="stSidebar"] div.stButton > button {
        background: linear-gradient(135deg, #1d4ed8 0%, #0891b2 100%) !important;
        color: #ffffff !important;
        border: 1px solid rgba(125, 211, 252, 0.55) !important;
        border-radius: 14px !important;
        min-height: 2.65rem;
        font-weight: 850 !important;
        box-shadow: 0 12px 28px rgba(14, 165, 233, 0.28) !important;
    }
    [data-testid="stSidebar"] div.stButton > button:hover {
        border-color: rgba(34, 211, 238, 0.95) !important;
        box-shadow: 0 16px 34px rgba(34, 211, 238, 0.32) !important;
        transform: translateY(-1px);
    }
    [data-testid="stSidebar"] [data-baseweb="select"] > div,
    [data-testid="stSidebar"] input,
    [data-testid="stSidebar"] textarea {
        background: rgba(15, 23, 42, 0.88) !important;
        border-color: rgba(96, 165, 250, 0.35) !important;
        color: #f8fafc !important;
        border-radius: 12px !important;
    }
    [data-testid="stSidebar"] [data-baseweb="tag"] {
        background: rgba(37, 99, 235, 0.35) !important;
        color: #eff6ff !important;
    }
    [data-testid="stSidebar"] [data-testid="stExpander"] {
        border: 2px solid rgba(96, 165, 250, 0.5);
        border-radius: 14px;
        background: rgba(15, 23, 42, 0.55);
        overflow: visible;
        margin-bottom: 12px;
    }
    [data-testid="stSidebar"] [data-testid="stExpander"] summary {
        color: #e0f2fe !important;
        font-weight: 850 !important;
        font-size: 1.05rem !important;
        padding: 14px 12px !important;
        cursor: pointer !important;
        background: linear-gradient(135deg, rgba(37, 99, 235, 0.45), rgba(6, 182, 212, 0.28)) !important;
        border-radius: 12px !important;
    }
    [data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {
        background: linear-gradient(135deg, rgba(37, 99, 235, 0.62), rgba(6, 182, 212, 0.38)) !important;
    }
    .sidebar-scan-box {
        padding: 12px 13px 4px;
        border-radius: 16px;
        border: 2px solid rgba(37, 99, 235, 0.48);
        background: rgba(15, 23, 42, 0.78);
        margin-bottom: 14px;
        direction: rtl;
    }
    [data-testid="stSidebar"] .sidebar-scan-box + div .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #2563eb, #06b6d4) !important;
        border: 2px solid rgba(147, 197, 253, 0.75) !important;
        color: #ffffff !important;
        font-weight: 900 !important;
        font-size: 1rem !important;
        min-height: 3rem !important;
        box-shadow: 0 10px 28px rgba(37, 99, 235, 0.45) !important;
    }
    [data-testid="stSidebar"] .stSlider [data-baseweb="slider"] > div > div {
        background: linear-gradient(90deg, #2563eb, #06b6d4) !important;
    }
    [data-testid="stSidebar"] [data-testid="stAlert"] {
        border-radius: 12px;
    }
    button[kind="secondary"],
    [data-baseweb="tab"] {
        color: #f8fafc !important;
        font-weight: 800 !important;
    }
    [data-baseweb="tab"][aria-selected="true"] {
        color: #ff6b6b !important;
        text-shadow: 0 0 10px rgba(255,107,107,0.35);
    }
    .metric-card {
        background:
            radial-gradient(circle at top right, rgba(56,189,248,0.34), transparent 34%),
            linear-gradient(135deg, rgba(37,99,235,0.86), rgba(30,64,175,0.78));
        padding: 14px 17px;
        border-radius: 18px;
        border-left: 4px solid #3b82f6;
        border-top: 1px solid rgba(224,242,254,0.28);
        box-shadow: 0 18px 42px rgba(2,6,23,0.30), inset 0 1px 0 rgba(255,255,255,.08);
        backdrop-filter: blur(18px);
        transition: transform .18s ease, box-shadow .18s ease;
    }
    .metric-card:hover {
        transform: none;
        box-shadow: 0 18px 42px rgba(2,6,23,0.30), inset 0 1px 0 rgba(255,255,255,.08);
    }
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div {
        position: relative;
        z-index: 2;
    }
    .status-badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 4px;
        color: white;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .band-badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 4px;
        color: white;
        font-weight: 600;
        font-size: 0.75rem;
        text-transform: uppercase;
    }
    .signal-card {
        background-color: #1e293b;
        padding: 16px;
        border-radius: 8px;
        margin-bottom: 12px;
        border-left: 4px solid #3b82f6;
    }
    .warning-text {
        color: #fbbf24;
        font-size: 0.9rem;
        margin-top: 4px;
    }
    .footer-note {
        color: #cbd5e1;
        font-size: 0.85rem;
        font-style: italic;
        text-align: center;
        margin-top: 24px;
    }
    .hero-card {
        background: linear-gradient(180deg, rgba(10, 22, 40, 0.98), rgba(15, 35, 62, 0.96));
        padding: 28px 30px;
        border-radius: 20px;
        border: 1px solid rgba(148, 163, 184, 0.22);
        box-shadow: 0 24px 60px rgba(2, 6, 23, 0.45);
        margin-bottom: 18px;
        position: relative;
        overflow: hidden;
    }
    .hero-title {
        color: #f8fafc;
        font-size: clamp(1.6rem, 2.5vw, 2.4rem);
        font-weight: 800;
        margin-bottom: 6px;
        letter-spacing: -0.02em;
    }
    .hero-subtitle {
        color: #94a3b8;
        font-size: 0.95rem;
        font-weight: 500;
    }
    .scanner-top {
        position: relative;
        margin: 0 0 1.25rem 0;
        border-radius: 22px;
        overflow: hidden;
        border: 1px solid rgba(212, 175, 55, 0.32);
        background:
            radial-gradient(120% 80% at 100% 0%, rgba(212, 175, 55, 0.14), transparent 50%),
            radial-gradient(90% 70% at 0% 100%, rgba(6, 182, 212, 0.12), transparent 45%),
            linear-gradient(165deg, #0a0c10 0%, #121820 55%, #0d1218 100%);
        box-shadow: 0 28px 70px rgba(2, 6, 23, 0.55);
        direction: rtl;
        pointer-events: none;
        user-select: none;
    }
    .scan-progress-profile {
        color: #fcd34d;
        font-family: 'Cinzel', 'Playfair Display', Georgia, serif;
        font-size: 0.9rem;
        font-weight: 700;
        margin: 0.15rem 0 0.1rem;
        direction: rtl;
        letter-spacing: 0.02em;
    }
    .scan-progress-label {
        color: #cbd5e1;
        font-size: 0.8rem;
        font-weight: 600;
        margin: 0.25rem 0;
        direction: rtl;
    }
    .advisory-hub {
        direction: rtl;
        margin: 2px 0 8px;
        padding: 12px 12px 10px;
        border-radius: 16px;
        border: 1px solid rgba(212, 175, 55, 0.4);
        background:
            radial-gradient(circle at 100% 0%, rgba(212, 175, 55, 0.12), transparent 42%),
            linear-gradient(160deg, rgba(30, 41, 59, 0.95), rgba(15, 23, 42, 0.98));
        box-shadow: 0 12px 28px rgba(2, 6, 23, 0.35);
        pointer-events: auto;
    }
    .advisory-ticker {
        color: #fde68a;
        font-size: 0.78rem;
        font-weight: 600;
        margin-bottom: 10px;
    }
    .advisory-tiles {
        display: grid;
        grid-template-columns: 1fr;
        gap: 8px;
    }
    .advisory-tile {
        display: block;
        text-decoration: none !important;
        padding: 11px 13px;
        border-radius: 13px;
        border: 1px solid rgba(255, 255, 255, 0.14);
        transition: transform 0.16s ease, box-shadow 0.16s ease;
    }
    .advisory-tile:hover {
        transform: translateY(-2px);
        box-shadow: 0 12px 26px rgba(0, 0, 0, 0.38);
    }
    .advisory-tile-gf {
        background: linear-gradient(135deg, rgba(37, 99, 235, 0.55), rgba(59, 130, 246, 0.28));
        border-color: rgba(147, 197, 253, 0.65);
    }
    .advisory-tile-tv {
        background: linear-gradient(135deg, rgba(79, 70, 229, 0.55), rgba(6, 182, 212, 0.32));
        border-color: rgba(129, 140, 248, 0.65);
    }
    .advisory-tile-fv {
        background: linear-gradient(135deg, rgba(22, 163, 74, 0.55), rgba(5, 150, 105, 0.3));
        border-color: rgba(134, 239, 172, 0.6);
    }
    .advisory-tile-kicker {
        display: block;
        font-size: 0.64rem;
        font-weight: 800;
        letter-spacing: 0.07em;
        text-transform: uppercase;
        color: rgba(255, 255, 255, 0.82);
        margin-bottom: 3px;
    }
    .advisory-tile-title {
        display: block;
        font-size: 0.96rem;
        font-weight: 850;
        color: #ffffff;
    }
    .advisory-tile-sub {
        display: block;
        font-size: 0.72rem;
        color: #e2e8f0;
        margin-top: 2px;
    }
    [data-testid="stSidebar"] [data-testid="stExpander"]:has(summary) {
        border-color: rgba(212, 175, 55, 0.35) !important;
        background: rgba(15, 23, 42, 0.65) !important;
    }
    [data-testid="stSidebar"] [data-testid="stExpander"] summary {
        color: #fde68a !important;
        font-weight: 850 !important;
    }
    .scan-panel-box {
        border: 1px solid rgba(96, 165, 250, 0.3);
        border-radius: 16px;
        padding: 2px 10px 12px;
        margin: 0 0 12px;
        background: rgba(15, 23, 42, 0.5);
    }
    .integrity-ok { color: #4ade80; font-weight: 700; }
    .integrity-warn { color: #fbbf24; font-weight: 700; }
    .scanner-top-glow {
        position: absolute;
        inset: 0;
        background:
            radial-gradient(ellipse 80% 60% at 100% 0%, rgba(14, 165, 233, 0.14), transparent 55%),
            radial-gradient(ellipse 60% 50% at 0% 100%, rgba(212, 175, 55, 0.08), transparent 50%);
        pointer-events: none;
    }
    .scanner-top-inner {
        position: relative;
        padding: 1.35rem 1.5rem 1.15rem;
    }
    .scanner-top-row {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 1rem;
        flex-wrap: wrap;
        margin-bottom: 0.85rem;
    }
    .scanner-top-brand {
        display: flex;
        align-items: center;
        gap: 0.85rem;
        min-width: 0;
    }
    .scanner-top-logo {
        width: 56px;
        height: 56px;
        border-radius: 16px;
        display: grid;
        place-items: center;
        font-size: 0.82rem;
        flex-shrink: 0;
    }
    .scanner-top-title {
        font-family: 'Cinzel', 'Playfair Display', Georgia, serif;
        background: linear-gradient(90deg, #fffbeb 0%, #fde68a 35%, #d4af37 62%, #fef3c7 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        font-size: clamp(1.4rem, 2.4vw, 2rem);
        font-weight: 800;
        line-height: 1.12;
        letter-spacing: 0.03em;
    }
    .scanner-top-sub {
        color: #94a3b8;
        font-size: 0.82rem;
        font-weight: 500;
        margin-top: 0.2rem;
        line-height: 1.4;
    }
    .scanner-top-badges {
        display: flex;
        flex-wrap: wrap;
        gap: 0.4rem;
        align-items: center;
        justify-content: flex-end;
    }
    .scanner-badge {
        display: inline-block;
        padding: 0.28rem 0.65rem;
        border-radius: 999px;
        font-size: 0.68rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        color: #e2e8f0;
        background: rgba(30, 41, 59, 0.85);
        border: 1px solid rgba(148, 163, 184, 0.28);
    }
    .scanner-badge-gold {
        color: #fef3c7;
        border-color: rgba(212, 175, 55, 0.45);
        background: rgba(120, 90, 20, 0.25);
    }
    .scanner-badge-live {
        color: #bbf7d0;
        border-color: rgba(34, 197, 94, 0.45);
        background: rgba(22, 101, 52, 0.28);
    }
    .scanner-top-meta {
        color: #cbd5e1;
        font-size: 0.8rem;
        font-weight: 600;
        margin-bottom: 1rem;
        padding-bottom: 0.85rem;
        border-bottom: 1px solid rgba(51, 65, 85, 0.65);
    }
    .scanner-kpi-grid {
        display: grid;
        grid-template-columns: repeat(6, minmax(0, 1fr));
        gap: 0.65rem;
    }
    @media (max-width: 1100px) {
        .scanner-kpi-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    }
    @media (max-width: 640px) {
        .scanner-kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    .scanner-kpi {
        padding: 0.65rem 0.75rem;
        border-radius: 14px;
        background: rgba(15, 23, 42, 0.72);
        border: 1px solid rgba(51, 65, 85, 0.55);
        border-top: 2px solid var(--kpi-accent, #38bdf8);
    }
    .scanner-kpi-label {
        color: #94a3b8;
        font-size: 0.68rem;
        font-weight: 700;
        margin-bottom: 0.25rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .scanner-kpi-value {
        color: #f8fafc;
        font-size: clamp(1.1rem, 1.8vw, 1.45rem);
        font-weight: 800;
        line-height: 1.1;
        font-variant-numeric: tabular-nums;
    }
    .scanner-market-strip {
        margin-top: 0.75rem;
        padding: 0.55rem 0.85rem;
        border-radius: 12px;
        background: rgba(15, 23, 42, 0.65);
        border: 1px solid rgba(51, 65, 85, 0.5);
        color: #e2e8f0;
        font-size: 0.82rem;
        font-weight: 600;
    }
    .setup-card {
        background:
            radial-gradient(circle at 82% 0%, rgba(56, 189, 248, 0.34), transparent 34%),
            radial-gradient(circle at 4% 12%, rgba(244,114,182,0.20), transparent 32%),
            linear-gradient(180deg, rgba(37,99,235,.86) 0%, rgba(30,41,59,.88) 100%);
        border-radius: 20px;
        padding: 15px 16px;
        border: 1px solid rgba(125,211,252,0.42);
        box-shadow: 0 18px 46px rgba(0,0,0,0.34), inset 0 1px 0 rgba(255,255,255,.08);
        min-height: 118px;
        margin-bottom: 10px;
        backdrop-filter: blur(16px);
    }
    .setup-symbol {
        color: #f8fafc;
        font-size: 1.35rem;
        font-weight: 800;
    }
    .setup-badge {
        display: inline-block;
        color: white;
        padding: 3px 9px;
        border-radius: 999px;
        font-weight: 700;
        font-size: 0.78rem;
        margin: 4px 0 8px;
    }
    .setup-text {
        color: #f1f5f9;
        font-size: 0.84rem;
        line-height: 1.45;
    }
    .chart-frame {
        background:
            radial-gradient(circle at top right, rgba(34,211,238,0.13), transparent 35%),
            linear-gradient(180deg, rgba(2,6,23,.94) 0%, rgba(15,23,42,.92) 100%);
        border: 1px solid rgba(125, 211, 252, 0.48);
        border-radius: 20px;
        padding: 12px;
        box-shadow:
            inset 0 0 44px rgba(37, 99, 235, 0.18),
            0 18px 42px rgba(2, 6, 23, 0.36);
        margin-bottom: 20px;
    }
    .pro-table-outer {
        width: 100%;
        max-width: 100%;
        overflow-x: hidden;
        overflow-y: visible;
        margin-bottom: 8px;
    }
    .pro-table-wrap {
        width: 100%;
        max-width: 100%;
        border-radius: 18px;
        border: 1px solid rgba(96,165,250,0.35);
        box-shadow: 0 18px 44px rgba(2,6,23,0.55);
        background: #020617;
        overflow: hidden;
    }
    table.pro-table {
        width: 100%;
        max-width: 100%;
        min-width: 0;
        table-layout: fixed;
        border-collapse: collapse;
        font-size: clamp(0.5rem, 0.42vw + 0.34rem, 0.72rem);
        color: #e5e7eb;
        direction: rtl;
    }
    .pro-table thead th {
        background: linear-gradient(180deg, #2563eb, #1d4ed8);
        color: #f8fafc;
        padding: clamp(2px, 0.35vw, 5px) clamp(2px, 0.45vw, 6px);
        text-align: right;
        border-bottom: 1px solid rgba(191,219,254,0.28);
        white-space: normal;
        line-height: 1.15;
        word-break: break-word;
        overflow-wrap: anywhere;
        hyphens: auto;
    }
    .pro-table tbody tr {
        background: rgba(15,23,42,0.94);
        border-bottom: 1px solid rgba(51,65,85,0.72);
    }
    .pro-table tbody tr:nth-child(even) { background: rgba(17,34,64,0.94); }
    .pro-table tbody tr:hover {
        background: rgba(30,64,175,0.42);
        box-shadow: inset 3px 0 0 #60a5fa;
    }
    .pro-table td {
        padding: clamp(2px, 0.35vw, 4px) clamp(2px, 0.45vw, 6px);
        vertical-align: middle;
        line-height: 1.15;
        white-space: normal;
        word-break: break-word;
        overflow-wrap: anywhere;
        max-width: 0;
    }
    @media (max-width: 1280px) {
        table.pro-table { font-size: clamp(0.48rem, 0.5vw + 0.3rem, 0.66rem); }
        .ticker-cell { font-size: clamp(0.62rem, 0.55vw + 0.42rem, 0.82rem) !important; }
        .prob-pill { min-width: 38px; padding: 2px 5px; font-size: 0.68rem; }
    }
    @media (max-width: 900px) {
        table.pro-table { font-size: clamp(0.44rem, 0.58vw + 0.24rem, 0.58rem); }
        .ticker-cell { font-size: clamp(0.56rem, 0.62vw + 0.36rem, 0.74rem) !important; }
        .setup-badge, .momentum-badge { font-size: 0.62rem; padding: 2px 5px; }
        .prob-pill { min-width: 34px; font-size: 0.62rem; }
    }
    .ticker-cell {
        color: #ffffff;
        font-weight: 950;
        font-size: .88rem;
        letter-spacing: .3px;
        text-shadow: 0 0 12px rgba(96,165,250,.45);
    }
    .ticker-link {
        color: #ffffff !important;
        text-decoration: none !important;
    }
    .ticker-link:hover {
        color: #93c5fd !important;
        text-decoration: underline !important;
    }
    .prob-pill {
        display: inline-block;
        min-width: 48px;
        text-align: center;
        padding: 2px 6px;
        border-radius: 999px;
        color: white;
        font-weight: 800;
        box-shadow: 0 0 16px rgba(34,197,94,0.25);
    }
    .small-muted { color: #94a3b8; font-size: 0.62rem; }
    .momentum-badge {
        display: inline-block;
        padding: 3px 7px;
        border-radius: 999px;
        color: #ffffff;
        font-size: .72rem;
        font-weight: 950;
        white-space: nowrap;
        box-shadow: 0 0 18px rgba(255,255,255,.12);
    }
    .heat-elite {
        background: linear-gradient(135deg, #7f1d1d, #dc2626, #f97316);
        box-shadow: 0 0 24px rgba(248,113,113,.34);
    }
    .heat-hot {
        background: linear-gradient(135deg, #92400e, #f59e0b);
        box-shadow: 0 0 22px rgba(245,158,11,.30);
    }
    .heat-strong {
        background: linear-gradient(135deg, #166534, #22c55e);
        box-shadow: 0 0 20px rgba(34,197,94,.26);
    }
    .heat-watch {
        background: linear-gradient(135deg, #075985, #06b6d4);
        box-shadow: 0 0 18px rgba(6,182,212,.22);
    }
    .momentum-card {
        position: relative;
        overflow: hidden;
    }
    .momentum-card::before {
        content: "";
        position: absolute;
        inset: 0 0 auto 0;
        height: 4px;
        background: linear-gradient(90deg, #38bdf8, #a78bfa);
    }
    .momentum-card.heatbar-elite::before { background: linear-gradient(90deg,#dc2626,#f97316); }
    .momentum-card.heatbar-hot::before { background: linear-gradient(90deg,#f59e0b,#facc15); }
    .momentum-card.heatbar-strong::before { background: linear-gradient(90deg,#16a34a,#22c55e); }
    .momentum-card.heatbar-watch::before { background: linear-gradient(90deg,#0284c7,#06b6d4); }
    .chart-card-premium {
        border-radius: 22px;
        padding: 16px 16px 12px;
        margin-bottom: 14px;
        background:
            radial-gradient(circle at 100% 0%, rgba(212, 175, 55, 0.14), transparent 40%),
            linear-gradient(165deg, rgba(15, 23, 42, 0.96), rgba(30, 41, 59, 0.92));
        border: 1px solid rgba(96, 165, 250, 0.35);
        box-shadow: 0 22px 50px rgba(2, 6, 23, 0.45);
    }
    .chart-card-aplus {
        border-color: rgba(212, 175, 55, 0.75);
        box-shadow: 0 0 28px rgba(212, 175, 55, 0.18), 0 22px 50px rgba(2, 6, 23, 0.45);
    }
    .chart-card-watch {
        border-color: rgba(234, 179, 8, 0.55);
    }
    .chart-card-head {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 10px;
        margin-bottom: 8px;
        direction: rtl;
    }
    .chart-card-symbol {
        font-size: 1.55rem;
        font-weight: 900;
        color: #fffbeb;
        letter-spacing: 0.02em;
    }
    .chart-card-metrics {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        justify-content: flex-end;
    }
    .chart-card-meta {
        color: #cbd5e1;
        font-size: 0.8rem;
        line-height: 1.5;
        margin: 6px 0 10px;
        direction: rtl;
    }
    .cloud-access-url {
        color: #fde68a !important;
        font-weight: 800;
        font-size: 0.88rem;
        word-break: break-all;
        text-decoration: none !important;
    }
    .cloud-access-url:hover { color: #fef3c7 !important; text-decoration: underline !important; }
    .rank-delta-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 999px;
        font-size: 0.72rem;
        font-weight: 850;
    }
    .rank-delta-up { background: rgba(34, 197, 94, 0.25); color: #86efac; border: 1px solid rgba(74, 222, 128, 0.5); }
    .rank-delta-down { background: rgba(239, 68, 68, 0.22); color: #fca5a5; border: 1px solid rgba(248, 113, 113, 0.45); }
    .rank-delta-new { background: rgba(56, 189, 248, 0.22); color: #7dd3fc; border: 1px solid rgba(56, 189, 248, 0.45); }
    .rank-delta-flat { background: rgba(100, 116, 139, 0.25); color: #cbd5e1; }
    .ticker-advice-card {
        direction: rtl;
        padding: 12px 14px;
        margin: 8px 0 10px;
        border-radius: 16px;
        border: 1px solid rgba(212, 175, 55, 0.45);
        background: linear-gradient(160deg, rgba(30, 41, 59, 0.95), rgba(15, 23, 42, 0.98));
    }
    .ticker-advice-title {
        color: #fde68a;
        font-weight: 900;
        font-size: 1rem;
        margin-bottom: 4px;
    }
    .ticker-advice-meta {
        color: #94a3b8;
        font-size: 0.78rem;
        margin-bottom: 8px;
    }
    .ticker-advice-list {
        margin: 0;
        padding-right: 1.1rem;
        color: #e2e8f0;
        font-size: 0.82rem;
        line-height: 1.55;
    }
    .rank-movers-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 12px;
        direction: rtl;
        margin: 0.5rem 0 1rem;
    }
    .rank-mover-box {
        padding: 12px;
        border-radius: 14px;
        border: 1px solid rgba(96, 165, 250, 0.28);
        background: rgba(15, 23, 42, 0.75);
        font-size: 0.8rem;
        line-height: 1.5;
        color: #e2e8f0;
    }
    .top-movers-grid {
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 12px;
        direction: rtl;
    }
    .top-mover-card {
        position: relative;
        overflow: hidden;
        min-height: 150px;
        padding: 17px;
        border-radius: 22px;
        border: 1px solid rgba(255,255,255,0.18);
        background:
            radial-gradient(circle at 90% 0%, rgba(248,113,113,0.36), transparent 30%),
            radial-gradient(circle at 8% 4%, rgba(34,211,238,0.25), transparent 31%),
            linear-gradient(145deg, rgba(30,41,59,0.86), rgba(15,23,42,0.88));
        box-shadow: 0 22px 58px rgba(2,6,23,0.36), inset 0 1px 0 rgba(255,255,255,.10);
        backdrop-filter: blur(18px);
        transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
    }
    .top-mover-card:hover {
        transform: translateY(-4px) scale(1.012);
        border-color: rgba(251,191,36,.58);
        box-shadow: 0 28px 70px rgba(251,113,133,0.22), inset 0 1px 0 rgba(255,255,255,.16);
    }
    .top-mover-card::before {
        content: "";
        position: absolute;
        inset: 0 0 auto 0;
        height: 5px;
        background: linear-gradient(90deg, #38bdf8, #a78bfa);
    }
    .top-mover-card.heatbar-elite::before { background: linear-gradient(90deg,#dc2626,#f97316); }
    .top-mover-card.heatbar-hot::before { background: linear-gradient(90deg,#f59e0b,#facc15); }
    .top-mover-card.heatbar-strong::before { background: linear-gradient(90deg,#16a34a,#22c55e); }
    .top-mover-card.heatbar-watch::before { background: linear-gradient(90deg,#0284c7,#06b6d4); }
    .top-mover-symbol {
        color: #ffffff;
        font-size: 1.38rem;
        font-weight: 950;
        letter-spacing: .4px;
        text-shadow: 0 0 22px rgba(125,211,252,.38);
    }
    .top-mover-meta {
        color: #cbd5e1;
        font-size: .74rem;
        line-height: 1.45;
        margin-top: 8px;
    }
    .top-mover-score {
        display: flex;
        gap: 7px;
        flex-wrap: wrap;
        margin-top: 10px;
    }
    .strategy-card {
        min-height: 162px;
        padding: 16px;
        border-radius: 22px;
        border: 1px solid rgba(125,211,252,0.32);
        background:
            radial-gradient(circle at top left, rgba(56,189,248,0.30), transparent 34%),
            radial-gradient(circle at bottom right, rgba(168,85,247,0.22), transparent 34%),
            linear-gradient(145deg, rgba(30,64,175,0.78), rgba(30,41,59,0.82));
        box-shadow: 0 18px 44px rgba(2,6,23,0.30), inset 0 1px 0 rgba(255,255,255,.08);
        direction: rtl;
        backdrop-filter: blur(16px);
        transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease;
    }
    .strategy-card:hover {
        transform: translateY(-3px);
        border-color: rgba(34,211,238,0.68);
        box-shadow: 0 24px 60px rgba(34,211,238,0.16), inset 0 1px 0 rgba(255,255,255,.12);
    }
    .strategy-card.active {
        border-color: rgba(34,197,94,0.78);
        box-shadow: 0 0 0 1px rgba(34,197,94,0.35), 0 20px 50px rgba(22,163,74,0.18);
    }
    .strategy-title {
        color: #f8fafc;
        font-size: 1.02rem;
        font-weight: 900;
        line-height: 1.25;
        min-height: 2.5rem;
    }
    .strategy-stats {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 8px;
        margin: 12px 0;
    }
    .strategy-stat {
        padding: 7px 8px;
        border-radius: 12px;
        background: rgba(15,23,42,0.78);
        border: 1px solid rgba(148,163,184,0.15);
    }
    .strategy-stat span {
        display: block;
        color: #94a3b8;
        font-size: .64rem;
        font-weight: 700;
    }
    .strategy-stat strong {
        color: #f8fafc;
        font-size: .94rem;
    }
    .strategy-tickers {
        color: #bfdbfe;
        font-size: .75rem;
        line-height: 1.45;
    }
    div.stButton > button {
        background: linear-gradient(135deg, #1e3a8a, #2563eb) !important;
        color: #f8fafc !important;
        border: 1px solid rgba(96,165,250,0.55) !important;
        border-radius: 13px !important;
        font-weight: 850 !important;
        box-shadow: 0 10px 26px rgba(2,6,23,0.34) !important;
    }
    div.stButton > button:hover {
        background: linear-gradient(135deg, #1d4ed8, #0f766e) !important;
        color: #ffffff !important;
        border-color: rgba(125,211,252,0.9) !important;
    }
    div.stButton > button:focus,
    div.stButton > button:active {
        color: #ffffff !important;
        border-color: rgba(34,197,94,0.95) !important;
        box-shadow: 0 0 0 2px rgba(34,197,94,0.28) !important;
    }
    .strategy-summary-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 12px;
        direction: rtl;
        margin-bottom: 12px;
    }
    .strategy-summary-card {
        min-height: 94px;
        padding: 13px 15px;
        border-radius: 20px;
        border: 1px solid rgba(125,211,252,0.32);
        background:
            radial-gradient(circle at top right, rgba(96,165,250,0.34), transparent 32%),
            linear-gradient(145deg, rgba(37,99,235,0.76), rgba(30,41,59,0.80));
        box-shadow: 0 16px 40px rgba(2,6,23,0.26), inset 0 1px 0 rgba(255,255,255,.08);
        overflow: hidden;
        backdrop-filter: blur(16px);
    }
    .strategy-summary-card .label {
        color: #93c5fd;
        font-size: .72rem;
        font-weight: 800;
        margin-bottom: 5px;
    }
    .strategy-summary-card .value {
        color: #f8fafc;
        font-size: clamp(.88rem, 1.05vw, 1.18rem);
        font-weight: 950;
        line-height: 1.25;
        word-break: break-word;
    }
    .strategy-reset-card {
        padding: 14px 16px;
        border-radius: 20px;
        border: 1px solid rgba(74,222,128,0.42);
        background:
            radial-gradient(circle at 95% 0%, rgba(34,197,94,0.34), transparent 28%),
            radial-gradient(circle at 8% 6%, rgba(34,211,238,0.22), transparent 28%),
            linear-gradient(145deg, rgba(6,78,59,0.80), rgba(15,23,42,0.82));
        color: #f8fafc;
        direction: rtl;
        box-shadow: 0 18px 44px rgba(22,163,74,0.16), inset 0 1px 0 rgba(255,255,255,.10);
    }
    .strategy-reset-title {
        font-weight: 950;
        font-size: 1rem;
        margin-bottom: 3px;
    }
    .strategy-reset-subtitle {
        color: #bbf7d0;
        font-size: .78rem;
    }
    @media (max-width: 1500px) {
        .top-movers-grid {
            grid-template-columns: repeat(3, minmax(0, 1fr));
        }
    }
    @media (max-width: 1100px) {
        .top-movers-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }
        .strategy-summary-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }
        .strategy-stats {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }
    }
    @media (max-width: 700px) {
        .top-movers-grid,
        .strategy-summary-grid {
            grid-template-columns: 1fr;
        }
        .hero-card {
            padding: 22px;
        }
        .hero-title {
            font-size: 1.75rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# =============================================================================
# Data loading
# =============================================================================

def find_latest_report() -> Path | None:
    """Find the most recent CSV report in data/reports/."""
    if not REPORTS_DIR.exists():
        return None
    csv_files = sorted(REPORTS_DIR.glob("*_report.csv"), reverse=True)
    return csv_files[0] if csv_files else None


def find_summary_for(csv_path: Path) -> Path | None:
    """Find the matching summary.txt file for a given CSV report."""
    summary_path = csv_path.parent / csv_path.name.replace("_report.csv", "_summary.txt")
    return summary_path if summary_path.exists() else None


def report_variant_paths(main_report_path: Path) -> dict[str, Path]:
    """Return the related report CSV paths for one run date."""
    return {
        "Main Report": main_report_path,
        "Watchlist": main_report_path.parent / main_report_path.name.replace("_report.csv", "_watchlist.csv"),
        "Rejected": main_report_path.parent / main_report_path.name.replace("_report.csv", "_rejected.csv"),
    }


def list_all_reports() -> list[Path]:
    """List official CSV reports, newest first (skips test/bench/legacy junk)."""
    if not REPORTS_DIR.exists():
        return []
    paths = [p for p in REPORTS_DIR.glob("*_report.csv") if is_official_report_csv(p)]
    return sorted(paths, key=lambda path: path.stat().st_mtime, reverse=True)


def _report_path_from_job() -> Path | None:
    """Resolve report CSV from cloud scan job / session (when glob misses a fresh file)."""
    names: list[str] = []
    try:
        from src.cloud_scan_job import get_status

        job = get_status()
        if job.get("report_file"):
            names.append(str(job["report_file"]))
    except Exception:
        pass
    pref = st.session_state.get("last_scan_report_file", "")
    if pref:
        names.append(str(pref))
    seen: set[str] = set()
    for raw in names:
        name = Path(raw).name
        if not name or name in seen:
            continue
        seen.add(name)
        path = REPORTS_DIR / name
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def _discover_report_paths() -> list[Path]:
    """Official reports plus any job-indicated file not yet in the official list."""
    reports = list_all_reports()
    extra = _report_path_from_job()
    if extra and extra not in reports:
        reports = [extra] + reports
    return reports


def _maybe_reload_after_scan_ok() -> None:
    """Once per completed scan: clear cache and rerun so the new CSV appears in the UI."""
    try:
        from src.cloud_scan_job import get_status

        job = get_status()
    except Exception:
        return
    if job.get("state") != "ok" or not job.get("report_file"):
        return
    rid = f"{job.get('report_file')}:{job.get('profile', '')}"
    if st.session_state.get("scan_ok_reloaded_for") == rid:
        return
    st.session_state["scan_ok_reloaded_for"] = rid
    st.session_state["last_scan_report_file"] = job["report_file"]
    st.cache_data.clear()
    _rerun_app()


def _sidebar_selector(label: str, options: list, *, index: int, key: str, format_func=None):
    """Use radio on Render — avoids Streamlit Selectbox chunk load failures in some browsers."""
    if os.getenv("RENDER", "").lower() == "true" and len(options) <= 8:
        labels = [format_func(o) if format_func else str(o) for o in options]
        choice = st.radio(label, options=labels, index=min(index, len(labels) - 1), key=key)
        return options[labels.index(choice)]
    return st.selectbox(
        label,
        options=options,
        index=index,
        format_func=format_func,
        key=key,
    )


def run_professional_scan_from_dashboard(profile_id: str) -> tuple[bool, str]:
    from src.scan_profiles import apply_profile_to_env, get_profile

    ok_key, key_msg = _preflight_polygon_key()
    if not ok_key:
        return False, key_msg

    polygon_key = _resolve_polygon_api_key()
    profile = get_profile(profile_id)
    apply_profile_to_env(profile)
    universe_csv = Path(os.getenv("SCANNER_UNIVERSE_CSV", "data/universe/polygon_liquid_us.csv"))
    sector_map = Path(os.getenv("SCANNER_SECTOR_MAP", "data/universe/sector_map.csv"))
    timeout_seconds = profile.timeout_seconds
    override = os.getenv("SCAN_TIMEOUT_SECONDS", "").strip()
    if override.isdigit():
        timeout_seconds = int(override)
    timeout_seconds = max(timeout_seconds, profile.timeout_seconds + 60)

    cmd = [
        sys.executable,
        "scripts/run_pro_scanner.py",
        "--profile",
        profile.id,
        "--sector-map",
        str(sector_map),
        "--output-suffix",
        os.getenv("SCANNER_OUTPUT_SUFFIX", profile.output_suffix),
    ]
    if universe_csv.exists():
        cmd.extend(["--universe-csv", str(universe_csv)])
    if _is_cloud_space():
        cmd.extend(["--workers", str(CLOUD_SCAN_WORKERS)])

    scan_env = os.environ.copy()
    scan_env["POLYGON_API_KEY"] = polygon_key
    scan_env["DATA_PROVIDER"] = "polygon"
    if _is_cloud_space():
        scan_env["SCAN_WORKERS"] = str(CLOUD_SCAN_WORKERS)

    try:
        completed = subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=scan_env,
        )
    except subprocess.TimeoutExpired:
        hint = ""
        if _is_cloud_space():
            hint = " בענן הרץ סריקה מלאה מהמחשב והעלה את קובץ הדוח ל-data/reports/."
        return False, f"הסריקה עברה את מגבלת הזמן ({timeout_seconds} שניות).{hint}"

    output = "\n".join(part for part in [completed.stdout, completed.stderr] if part.strip())
    if completed.returncode != 0 and _is_cloud_space() and "401" in output:
        output += "\n\nבדוק ש-POLYGON_API_KEY תקין ב-Secrets."
    return completed.returncode == 0, output[-5000:]


@st.cache_data(show_spinner=False)
def load_report(csv_path_str: str, file_size: int, file_mtime_ns: int) -> pd.DataFrame:
    """Load a CSV report, returning an empty frame when no data exists yet."""
    # file_size and file_mtime_ns are cache keys so Streamlit reloads changed reports.
    _ = (file_size, file_mtime_ns)
    csv_path = Path(csv_path_str)
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        df = pd.read_csv(csv_path)
    except EmptyDataError:
        return pd.DataFrame()

    # Older watchlist/rejected files use snake_case trade-plan columns.
    aliases = {
        "Entry Trigger": "entry_trigger",
        "Stop Loss": "stop_loss",
        "Target 1": "target_1",
        "Target 2": "target_2",
        "Risk/Reward": "risk_reward",
        "Invalidation": "invalidation",
        "Wait For": "what_to_wait_for",
    }
    for display_col, source_col in aliases.items():
        if display_col not in df.columns and source_col in df.columns:
            df[display_col] = df[source_col]
    for chart_col in ["גרף קטן", "גרף יומי", "גרף שבועי", "גרף שעתי"]:
        if chart_col in df.columns:
            df[chart_col] = df[chart_col].apply(_parse_sparkline)
    return df


def _parse_sparkline(value):
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def parse_date_from_filename(path: Path) -> str:
    """Extract YYYY-MM-DD from a filename like 2026-05-18_report.csv."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})_report\.csv", path.name)
    return m.group(1) if m else path.stem


_PROFILE_SUFFIX_HE = {
    "us_simple": "פשוטה",
    "us_medium": "בינונית",
    "us_full": "מקיפה",
}


def report_display_label(path: Path) -> str:
    """Unique label per report file (date + scan profile)."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})_(.+)_report\.csv", path.name)
    if m:
        date_part, suffix = m.group(1), m.group(2)
        he = _PROFILE_SUFFIX_HE.get(suffix, suffix.replace("_", " "))
        return f"{date_part} · {he} ({suffix})"
    m2 = re.match(r"(\d{4}-\d{2}-\d{2})_report\.csv", path.name)
    if m2:
        return m2.group(1)
    return path.stem


def _default_report_index(reports: list[Path], labels: list[str]) -> int:
    preferred = st.session_state.get("last_scan_report_file", "")
    if preferred:
        for idx, path in enumerate(reports):
            if path.name == preferred:
                return idx
    profile_id = st.session_state.get("last_scan_profile", "")
    suffix = {"simple": "us_simple", "medium": "us_medium", "full": "us_full"}.get(profile_id, "")
    if suffix:
        dated: list[tuple[str, int]] = []
        for idx, path in enumerate(reports):
            if f"_{suffix}_report.csv" in path.name:
                m = re.match(r"(\d{4}-\d{2}-\d{2})", path.name)
                dated.append((m.group(1) if m else "", idx))
        if dated:
            dated.sort(reverse=True)
            return dated[0][1]
    dated_all: list[tuple[str, int]] = []
    for idx, path in enumerate(reports):
        m = re.match(r"(\d{4}-\d{2}-\d{2})", path.name)
        dated_all.append((m.group(1) if m else "", idx))
    if dated_all:
        dated_all.sort(reverse=True)
        return dated_all[0][1]
    return 0


# =============================================================================
# Render helpers
# =============================================================================

def status_badge(status: str) -> str:
    color = STATUS_COLORS.get(status, "#6b7280")
    return f'<span class="status-badge" style="background-color: {color};">{status}</span>'


def band_badge(band: str) -> str:
    color = BAND_COLORS.get(band, "#475569")
    label = BAND_LABELS.get(band, band.upper())
    return f'<span class="band-badge" style="background-color: {color};">{label}</span>'


def metric_card(label: str, value: str, accent: str = "#3b82f6") -> str:
    return (
        f'<div class="metric-card" style="border-left-color: {accent};">'
        f'<div style="color: #94a3b8; font-size: 0.85rem;">{label}</div>'
        f'<div style="color: #f1f5f9; font-size: 1.5rem; font-weight: 700;">{value}</div>'
        f"</div>"
    )



def _scanner_kpi_cell(label: str, value: str, accent: str) -> str:
    return (
        f'<div class="scanner-kpi" style="--kpi-accent: {accent};">'
        f'<div class="scanner-kpi-label">{html.escape(label)}</div>'
        f'<div class="scanner-kpi-value">{html.escape(str(value))}</div>'
        f"</div>"
    )


def _expected_universe_size() -> int:
    uni = ROOT / "data" / "universe" / "polygon_liquid_us.csv"
    if not uni.exists():
        return 2114
    try:
        return len(pd.read_csv(uni))
    except Exception:
        return 2114


def _scan_coverage_stats(df: pd.DataFrame) -> tuple[int, int, float]:
    expected = _expected_universe_size()
    rows = len(df)
    try:
        from src.cloud_scan_job import get_status

        job = get_status()
    except Exception:
        job = {}
    usable = int(job.get("symbols_with_usable_data", 0) or 0)
    if usable <= 0 and "סימבול" in df.columns:
        usable = int(df["סימבול"].nunique())
    coverage = float(job.get("coverage_pct", 0) or 0)
    if coverage <= 0 and expected:
        coverage = round(100.0 * min(usable, rows) / expected, 1)
    return expected, usable or rows, coverage


def _preflight_polygon_key_cached() -> tuple[bool, str]:
    """Cached Polygon check — avoids HTTP on every sidebar rerun."""
    cache = st.session_state.get("_polygon_preflight_cache")
    if isinstance(cache, dict) and cache.get("ok") is not None:
        return bool(cache["ok"]), str(cache.get("msg", ""))
    ok, msg = _preflight_polygon_key()
    st.session_state["_polygon_preflight_cache"] = {"ok": ok, "msg": msg}
    return ok, msg


def _auto_scan_on_entry_enabled() -> bool:
    return os.getenv("AUTO_SCAN_ON_ENTRY", "true").lower() not in {"0", "false", "no"}


def _maybe_auto_scan_on_entry(profile_id: str) -> None:
    """Start a full scan once per session when the user opens the scanner."""
    if not _auto_scan_on_entry_enabled():
        return
    if st.session_state.get("auto_scan_on_entry_done"):
        return
    if _discover_report_paths():
        st.session_state["auto_scan_on_entry_done"] = True
        return

    from src.cloud_scan_job import get_status, is_scan_running, start_full_scan

    if is_scan_running():
        st.session_state["auto_scan_on_entry_done"] = True
        return

    ok_pf, pf_msg = _preflight_polygon_key_cached()
    if not ok_pf:
        st.session_state["polygon_scan_error"] = pf_msg
        st.session_state["auto_scan_on_entry_done"] = True
        return

    started, _msg = start_full_scan(profile_id)
    st.session_state["auto_scan_on_entry_done"] = True
    if started:
        st.session_state["last_scan_profile"] = profile_id


def _render_cloud_scan_progress() -> None:
    from src.cloud_scan_job import get_scan_progress, get_status

    job = get_status()
    state = job.get("state", "idle")
    if state == "idle":
        return
    prog = job.get("progress") or get_scan_progress()
    pct = min(1.0, max(0.0, int(prog.get("percent", 0)) / 100.0))
    st.progress(pct)
    if state == "ok":
        _maybe_reload_after_scan_ok()
    elif state == "error":
        st.error(str(job.get("message", "שגיאה")))


def _render_institutional_scanner_header(
    df: pd.DataFrame,
    report_label: str,
    report_filename: str = "",
) -> None:
    """Top header — סורק הזהב."""
    profile_he = ""
    for suffix, he in _PROFILE_SUFFIX_HE.items():
        if suffix in report_filename:
            profile_he = he
            break

    scanned = len(df)
    a_plus = int((df["רמה"] == "A+ Setup").sum()) if "רמה" in df.columns else 0
    watch = int((df["רמה"] == "Watchlist").sum()) if "רמה" in df.columns else 0
    early = int((df["רמה"] == "Early Momentum").sum()) if "רמה" in df.columns else 0
    best = int(df["הסתברות %"].max()) if not df.empty and "הסתברות %" in df.columns else 0

    profile_badge = (
        f'<span class="scanner-badge scanner-badge-gold">{html.escape(profile_he)}</span>'
        if profile_he
        else ""
    )

    expected, usable, coverage = _scan_coverage_stats(df)
    cov_class = "integrity-ok" if coverage >= 95 else "integrity-warn"
    integrity_line = (
        f'<span class="{cov_class}">כיסוי דאטה {coverage}%</span> '
        f"({usable:,}/{expected:,} מניות)"
    )

    market_strip = ""
    if not df.empty and {"מצב שוק", "ציון שוק", "אישור שוק ללונג"}.issubset(df.columns):
        market_row = df.iloc[0]
        support = str(market_row["אישור שוק ללונג"])
        border = "rgba(34, 197, 94, 0.35)" if support == "תומך" else "rgba(245, 158, 11, 0.35)"
        market_strip = (
            f'<div class="scanner-market-strip" style="border-color: {border};">'
            f"שוק: {html.escape(str(market_row['מצב שוק']))} · "
            f"ציון {html.escape(str(int(market_row['ציון שוק'])))}/100 · "
            f"{html.escape(support)}"
            f"</div>"
        )

    st.markdown(
        f"""
        <div class="scanner-top">
            <div class="scanner-top-glow"></div>
            <div class="scanner-top-inner">
                <div class="scanner-top-row">
                    <div class="scanner-top-brand">
                        <div class="scanner-top-logo gold-logo-mark">{LOGO_MARK}</div>
                        <div>
                            <div class="scanner-top-title">{html.escape(BRAND_HE)}</div>
                            <div class="scanner-top-sub">
                                {html.escape(BRAND_EN)} · US Equities · לונג בלבד
                            </div>
                        </div>
                    </div>
                    <div class="scanner-top-badges">
                        <span class="scanner-badge scanner-badge-live">LIVE</span>
                        <span class="scanner-badge scanner-badge-universe">US</span>
                        {profile_badge}
                    </div>
                </div>
                <div class="scanner-top-meta">
                    דוח: {html.escape(report_label)} · {integrity_line}
                </div>
                <div class="scanner-kpi-grid">
                    {_scanner_kpi_cell("נסרקו", f"{scanned:,}", "#38bdf8")}
                    {_scanner_kpi_cell("A+ Setup", str(a_plus), "#22c55e")}
                    {_scanner_kpi_cell("Watchlist", str(watch), "#eab308")}
                    {_scanner_kpi_cell("Early", str(early), "#06b6d4")}
                    {_scanner_kpi_cell("ציון מוביל", f"{best}/100", "#a855f7")}
                    {_scanner_kpi_cell("מיון", "הסתברות %", "#64748b")}
                </div>
                {market_strip}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _level_color(level: str) -> str:
    return {
        "A+ Setup": "#16a34a",
        "Watchlist": "#eab308",
        "Early Momentum": "#06b6d4",
        "לא מעניין כרגע": "#64748b",
        "אין דירוג": "#475569",
    }.get(str(level), "#3b82f6")


def render_signal_card(row: pd.Series) -> None:
    """Render a detailed card for one signal."""
    status = row["Status"]
    band = row["Score Band"]
    accent = STATUS_COLORS.get(status, "#3b82f6")

    header_html = (
        f'<div class="signal-card" style="border-left-color: {accent};">'
        f'<div style="display: flex; justify-content: space-between; align-items: center;">'
        f'  <div style="font-size: 1.3rem; font-weight: 700; color: #f1f5f9;">'
        f'    #{int(row["Rank"])} · {row["Ticker"]} · ${row["Current Price"]:.2f}'
        f'  </div>'
        f'  <div>'
        f'    {band_badge(band)} {status_badge(status)}'
        f'  </div>'
        f'</div>'
        f'<div style="color: #94a3b8; margin-top: 4px;">'
        f'  Score <strong style="color: #f1f5f9;">{int(row["Score"])}</strong> · '
        f'  {row["Setup Type"]} ({row["Scanner Mode"]}) · '
        f'  Today {row["% Change Today"]:+.1f}% · '
        f'  RVOL {row["RVOL"]:.1f}x'
        f'</div>'
        f'</div>'
    )
    st.markdown(header_html, unsafe_allow_html=True)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(metric_card("Entry Trigger", f"${row['Entry Trigger']:.2f}", "#3b82f6"), unsafe_allow_html=True)
    with col2:
        st.markdown(metric_card("Stop Loss", f"${row['Stop Loss']:.2f}", "#dc2626"), unsafe_allow_html=True)
    with col3:
        st.markdown(metric_card("Target 1", f"${row['Target 1']:.2f}", "#16a34a"), unsafe_allow_html=True)
    with col4:
        st.markdown(metric_card("Risk / Reward", f"{row['Risk/Reward']:.1f}", "#a855f7"), unsafe_allow_html=True)

    # Narrative sections
    st.markdown("**Reason**")
    st.write(row["Reason"])

    st.markdown("**Invalidation**")
    st.write(row["Invalidation"])

    st.markdown("**Wait for**")
    st.write(row["Wait For"])

    if pd.notna(row.get("Warnings", "")) and str(row["Warnings"]).strip():
        warnings = str(row["Warnings"]).split(";")
        for w in warnings:
            w = w.strip()
            if w:
                st.markdown(f'<div class="warning-text">⚠ {w}</div>', unsafe_allow_html=True)

    # Stats expander
    with st.expander("Indicator details"):
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**Trend:** {row['Trend']}")
            st.write(f"**Price vs SMA20:** {row['Price vs SMA20']}")
            st.write(f"**Price vs SMA50:** {row['Price vs SMA50']}")
            st.write(f"**Dist from SMA20:** {row['Dist from SMA20 %']:+.2f}%")
            st.write(f"**Dist from SMA50:** {row['Dist from SMA50 %']:+.2f}%")
            st.write(f"**ATR Extension:** {row['ATR Extension']:.2f}x")
            st.write(f"**ATR(14):** ${row['ATR(14)']:.2f}")
        with col2:
            st.write(f"**Volume:** {int(row['Volume']):,}")
            st.write(f"**Avg Volume 20d:** {int(row['Avg Volume 20d']):,}")
            st.write(f"**Dollar Volume 20d:** ${int(row['Dollar Volume 20d']):,}")
            st.write(f"**20d High:** ${row['20d High']:.2f}")
            st.write(f"**50d High:** ${row['50d High']:.2f}")
            st.write(f"**52w High:** {row['52w High']}")
            st.write(f"**Target 2:** ${row['Target 2']:.2f}")


def _render_scan_controls(*, key_prefix: str = "sidebar_scan") -> None:
    """Scan profile picker + run button + progress (UI only; lifecycle runs in main)."""
    from src.scan_profiles import list_profiles

    profiles = list_profiles()
    profile_labels = {p.id: p.label_he for p in profiles}
    default_profile = _default_scan_profile_id()
    profile_ids = [p.id for p in profiles]
    selected_profile = _sidebar_selector(
        "רמת סריקה",
        profile_ids,
        index=profile_ids.index(default_profile),
        key=f"{key_prefix}_profile_select",
        format_func=lambda pid: profile_labels[pid],
    )
    selected = next(p for p in profiles if p.id == selected_profile)

    from src.cloud_scan_job import get_status, start_full_scan

    _render_cloud_scan_progress()

    scan_clicked = st.button(
        f"▶ סריקה — {selected.label_he}",
        use_container_width=True,
        type="primary",
        key=f"{key_prefix}_run_btn",
    )
    if scan_clicked:
        if _is_cloud_space():
            ok_pf, pf_msg = _preflight_polygon_key_cached()
            if not ok_pf:
                st.error(pf_msg)
            else:
                started, _msg = start_full_scan(selected_profile)
                if started:
                    st.session_state["last_scan_profile"] = selected_profile
                    st.session_state.pop("_polygon_preflight_cache", None)
                    st.session_state.pop("auto_scan_on_entry_done", None)
                    _rerun_app()
        else:
            with st.spinner("סורק…"):
                ok, output = run_professional_scan_from_dashboard(selected_profile)
            st.cache_data.clear()
            if ok:
                for line in output.splitlines():
                    if line.startswith("report_file="):
                        st.session_state["last_scan_report_file"] = line.split("=", 1)[-1].strip()
                st.session_state["last_scan_profile"] = selected_profile
                _rerun_app()
            else:
                st.error("הסריקה נכשלה.")

    job = get_status()
    if job.get("state") == "ok" and job.get("report_file"):
        st.session_state["last_scan_report_file"] = job["report_file"]
        st.session_state["last_scan_profile"] = job.get("profile", selected_profile)


def _render_scan_sidebar_panel(*, key_prefix: str = "sidebar_scan") -> None:
    """Scan controls inside the sidebar panel."""
    _render_sidebar_section("חלונית סריקה")
    _render_scan_controls(key_prefix=key_prefix)


# =============================================================================
# Main app
# =============================================================================

def main() -> None:
    _require_dashboard_password()
    _init_scan_ui_state()
    _handle_cloud_scan_lifecycle()
    # --- Sidebar: report selection ---
    with st.sidebar:
        _render_scan_progress_panel()
        _render_polygon_key_setup()
        _render_scan_sidebar_tab()
        if _scan_panel_enabled() and st.session_state.get("scan_panel_open", False):
            try:
                _render_scan_sidebar_panel()
            except Exception as exc:
                st.error(f"שגיאה במקטע סריקה: {exc}")

        _render_sidebar_brand()
        _render_cloud_access_panel()

        _render_sidebar_section("דוח")
        reports = _discover_report_paths()
        csv_path = None
        selected_date = ""
        selected_report_type = ""
        if not reports:
            job_path = _report_path_from_job()
            if job_path:
                reports = [job_path]
        if not reports:
            st.warning("אין דוח עדיין")
            if st.button("🔄 רענן דף", key="refresh_no_report"):
                st.cache_data.clear()
                _rerun_app()
        else:
            report_labels = [report_display_label(p) for p in reports]
            default_report_index = _default_report_index(reports, report_labels)
            selected_label = _sidebar_selector(
                "תאריך דוח",
                report_labels,
                index=default_report_index,
                key="report_date_full_scan_default",
            )
            main_report_path = reports[report_labels.index(selected_label)]
            selected_date = selected_label
            variant_paths = report_variant_paths(main_report_path)
            available_variants = {
                label: path for label, path in variant_paths.items()
                if path.exists()
            }
            selected_report_type = _sidebar_selector(
                "סוג דוח",
                list(available_variants.keys()),
                index=0,
                key="report_type_select",
            )
            csv_path = available_variants[selected_report_type]

            mtime = datetime.fromtimestamp(csv_path.stat().st_mtime)
            _render_sidebar_file_card(
                csv_path.name,
                csv_path.stat().st_size / 1024,
                mtime.strftime("%d/%m/%Y %H:%M:%S"),
            )

    if csv_path is None:
        st.markdown("### אין דוח להצגה עדיין")
        job_path = _report_path_from_job()
        if job_path:
            st.warning(
                f"נמצא קובץ דוח `{job_path.name}` אבל לא נטען — לחץ **רענן דף** "
                "או Deploy latest ב-Render."
            )
            if st.button("🔄 טען דוח", key="force_load_report", type="primary"):
                st.session_state["last_scan_report_file"] = job_path.name
                st.cache_data.clear()
                _rerun_app()
        st.info(
            "**בענן (Render):** אם הסריקה הסתיימה (100%) ועדיין ריק — **רענן את הדף** (F5). "
            "שגיאת Selectbox בדפדפן: נסה Chrome / חלון פרטי."
        )
        st.caption(f"תיקיית דוחות: `{REPORTS_DIR}`")
        return

    # --- Load report ---
    csv_stat = csv_path.stat()
    df = load_report(str(csv_path), csv_stat.st_size, csv_stat.st_mtime_ns)

    if df.empty and len(df.columns) == 0:
        st.info("No report data yet — run the daily scan.")
        return

    if df.empty:
        st.info(
            f"{selected_report_type} generated, but it has no rows. "
            "Use the Report type dropdown to inspect Watchlist or Rejected candidates."
        )

    if "הסתברות %" in df.columns:
        st.session_state["active_report_filename"] = csv_path.name
        df, prev_report_date = attach_rank_delta(df, csv_path, load_report_fn=load_report)
        _render_hebrew_professional_dashboard(
            df, selected_date, selected_report_type, prev_report_date=prev_report_date
        )
        return

    # --- Sidebar: filters ---
    with st.sidebar:
        st.header("🔍 Filters")

        band_options = ["elite", "very_strong", "watch_only", "excluded"]
        available_bands = [b for b in band_options if b in df["Score Band"].unique()]
        default_bands = [b for b in available_bands if b != "excluded"]
        selected_bands = st.multiselect(
            "Score band",
            options=available_bands,
            default=default_bands,
            format_func=lambda b: BAND_LABELS.get(b, b),
        )

        status_options = sorted(df["Status"].unique())
        selected_statuses = st.multiselect(
            "Status",
            options=status_options,
            default=status_options,
        )

        scanner_options = sorted(df["Scanner Mode"].unique())
        selected_scanners = st.multiselect(
            "Scanner mode",
            options=scanner_options,
            default=scanner_options,
        )

        setup_options = sorted(df["Setup Type"].unique())
        selected_setups = st.multiselect(
            "Setup type",
            options=setup_options,
            default=setup_options,
        )

        ticker_filter = st.text_input(
            "Ticker (comma-separated, empty = all)",
            value="",
        ).strip().upper()

        min_score = st.slider("Minimum score", 0, 100, 0, step=5)
        if "Category" in df.columns:
            category_options = list(df["Category"].dropna().unique())
            selected_categories = st.multiselect(
                "Category",
                options=category_options,
                default=category_options,
            )
        else:
            selected_categories = []

    # --- Apply filters ---
    filtered = df.copy()
    if selected_bands:
        filtered = filtered[filtered["Score Band"].isin(selected_bands)]
    if selected_statuses:
        filtered = filtered[filtered["Status"].isin(selected_statuses)]
    if selected_scanners:
        filtered = filtered[filtered["Scanner Mode"].isin(selected_scanners)]
    if selected_setups:
        filtered = filtered[filtered["Setup Type"].isin(selected_setups)]
    if ticker_filter:
        tickers_wanted = {t.strip() for t in ticker_filter.split(",") if t.strip()}
        filtered = filtered[filtered["Ticker"].isin(tickers_wanted)]
    filtered = filtered[filtered["Score"] >= min_score]
    if selected_categories and "Category" in filtered.columns:
        filtered = filtered[filtered["Category"].isin(selected_categories)]
    filtered = filtered.sort_values("Score", ascending=False).reset_index(drop=True)

    # --- Top summary cards ---
    st.markdown(f"### {selected_report_type}: {selected_date}")

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.markdown(metric_card("Total signals", f"{len(df)}", "#3b82f6"), unsafe_allow_html=True)
    with col2:
        elite_n = int((df["Score Band"] == "elite").sum())
        st.markdown(metric_card("Elite (90+)", f"{elite_n}", "#16a34a"), unsafe_allow_html=True)
    with col3:
        strong_n = int((df["Score Band"] == "very_strong").sum())
        st.markdown(metric_card("Very strong (85-89)", f"{strong_n}", "#eab308"), unsafe_allow_html=True)
    with col4:
        trigger_n = int((df["Status"] == "Trigger").sum())
        st.markdown(metric_card("Triggers", f"{trigger_n}", "#16a34a"), unsafe_allow_html=True)
    with col5:
        st.markdown(metric_card("After filters", f"{len(filtered)}", "#a855f7"), unsafe_allow_html=True)

    st.markdown("---")

    # --- Tabs ---
    tab1, tab2, tab3, tab4 = st.tabs([
        "📋 Watchlist Table",
        "🎯 Top Setups (Detail)",
        "📄 Summary",
        "🔬 Why excluded?",
    ])

    # ----- Tab 1: table -----
    with tab1:
        st.markdown(f"**Showing {len(filtered)} of {len(df)} signals** "
                    f"(sorted by score)")

        if filtered.empty:
            st.info("No signals match the current filters. Try widening them in the sidebar.")
        else:
            # Compact display columns
            display_cols = [
                "Rank", "Symbol", "Last Close", "Percent Change", "Relative Volume",
                "Trend Status", "Breakout Status", "Score", "Category",
                "Reason Plain English", "Suggested Trigger", "Invalidation/Stop Area",
                "Risk Note", "Ticker", "Current Price", "Score Band", "Status",
                "Setup Type", "Scanner Mode", "% Change Today", "RVOL",
                "Entry Trigger", "Stop Loss", "Target 1", "Risk/Reward", "Wait For",
            ]
            available_cols = [c for c in display_cols if c in filtered.columns]
            display_df = filtered[available_cols].copy()

            st.dataframe(
                display_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Rank": st.column_config.NumberColumn(width="small"),
                    "Score": st.column_config.ProgressColumn(
                        "Score",
                        min_value=0,
                        max_value=100,
                        format="%d",
                        width="small",
                    ),
                    "Current Price": st.column_config.NumberColumn(format="$%.2f"),
                    "Entry Trigger": st.column_config.NumberColumn(format="$%.2f"),
                    "Stop Loss": st.column_config.NumberColumn(format="$%.2f"),
                    "Target 1": st.column_config.NumberColumn(format="$%.2f"),
                    "% Change Today": st.column_config.NumberColumn(format="%+.2f%%"),
                    "RVOL": st.column_config.NumberColumn(format="%.2fx"),
                    "Risk/Reward": st.column_config.NumberColumn(format="%.1f"),
                    "Wait For": st.column_config.TextColumn(width="large"),
                },
            )

            # Download button
            csv_bytes = filtered.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="⬇️ Download filtered view as CSV",
                data=csv_bytes,
                file_name=f"{selected_date}_filtered.csv",
                mime="text/csv",
            )

    # ----- Tab 2: detail cards -----
    with tab2:
        if filtered.empty:
            st.info("No signals to display.")
        elif not {"Entry Trigger", "Stop Loss", "Target 1", "Target 2", "Risk/Reward", "Invalidation", "Wait For"}.issubset(filtered.columns):
            st.info("Detailed setup cards are available only for reports with full trade-plan columns.")
        else:
            detail_ready = filtered.dropna(subset=["Current Price", "Entry Trigger", "Stop Loss", "Target 1"])
            if detail_ready.empty:
                st.info("No detailed setup cards available for this view yet.")
            else:
                top_n = st.slider("How many top setups to show in detail", 1, min(20, len(detail_ready)),
                                  min(5, len(detail_ready)))
                for _, row in detail_ready.head(top_n).iterrows():
                    render_signal_card(row)
                    st.markdown("")  # spacer

    # ----- Tab 3: text summary -----
    with tab3:
        summary_path = find_summary_for(main_report_path)
        if summary_path is None:
            st.info("No text summary found for this report.")
        else:
            text = summary_path.read_text(encoding="utf-8")
            st.text(text)

    # ----- Tab 4: Why excluded? -----
    with tab4:
        st.markdown("### Why were signals excluded from the main report?")
        st.caption(
            "This view shows the system's selectivity in action. "
            "These signals were generated but did not meet the score threshold. "
            "They are NOT recommendations — they are shown for transparency."
        )

        # Find the matching rejected.csv and diagnostics.txt for the selected date.
        rejected_path = variant_paths["Rejected"]
        diag_path = main_report_path.parent / main_report_path.name.replace("_report.csv", "_diagnostics.txt")

        col_a, col_b = st.columns(2)
        with col_a:
            if rejected_path.exists():
                st.success(f"Rejected CSV found: {rejected_path.name}")
            else:
                st.warning("No _rejected.csv for this date.")
        with col_b:
            if diag_path.exists():
                st.success(f"Diagnostics found: {diag_path.name}")
            else:
                st.warning("No _diagnostics.txt for this date.")

        st.markdown("---")

        # Diagnostics report (text)
        if diag_path.exists():
            st.markdown("#### Rejection breakdown by reason")
            diag_text = diag_path.read_text(encoding="utf-8")
            st.text(diag_text)

        st.markdown("---")

        # Rejected CSV
        if rejected_path.exists():
            st.markdown("#### Rejected signals (sorted by score, highest first)")
            rej_stat = rejected_path.stat()
            rej_df = load_report(str(rejected_path), rej_stat.st_size, rej_stat.st_mtime_ns)
            if rej_df.empty:
                st.info("No rejected signals — every generated signal cleared the threshold.")
            else:
                st.markdown(f"**{len(rej_df)} rejected signals**")

                # Show only the most useful columns
                show_cols = [
                    "Rank", "Ticker", "Score", "Primary Rejection Reason",
                    "Setup Type", "Status", "Current Price", "% Change Today",
                    "RVOL", "Trend", "Dist from SMA20 %", "ATR Extension",
                    "Risk/Reward", "Warnings",
                ]
                avail = [c for c in show_cols if c in rej_df.columns]
                st.dataframe(
                    rej_df[avail],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Score": st.column_config.ProgressColumn(
                            "Score", min_value=0, max_value=100, format="%d", width="small"
                        ),
                        "Current Price": st.column_config.NumberColumn(format="$%.2f"),
                        "% Change Today": st.column_config.NumberColumn(format="%+.2f%%"),
                        "RVOL": st.column_config.NumberColumn(format="%.2fx"),
                        "Risk/Reward": st.column_config.NumberColumn(format="%.1f"),
                        "Dist from SMA20 %": st.column_config.NumberColumn(format="%+.2f%%"),
                        "ATR Extension": st.column_config.NumberColumn(format="%.2fx"),
                    },
                )

                st.download_button(
                    label="⬇️ Download rejected.csv",
                    data=rejected_path.read_bytes(),
                    file_name=rejected_path.name,
                    mime="text/csv",
                )

                # Per-reason summary table
                st.markdown("#### Counts per primary rejection reason")
                reason_counts = rej_df["Primary Rejection Reason"].value_counts().reset_index()
                reason_counts.columns = ["Primary Rejection Reason", "Count"]
                st.dataframe(reason_counts, hide_index=True, use_container_width=True)

        st.info(
            "💡 To see lower-quality candidates in the MAIN report, "
            "change `report_mode.active` to `exploratory` in config/settings.yaml. "
            "Exploratory mode lowers the score threshold to 60 and clearly marks "
            "those candidates as low-confidence."
        )

    # --- Footer ---
    st.markdown(
        '<div class="footer-note">'
        "This is a decision-support tool. It does not place trades, does not connect to a broker, "
        "and does not send alerts. Every setup requires your own analysis before any action."
        "</div>",
        unsafe_allow_html=True,
    )


def _render_rank_delta_summary(df: pd.DataFrame, prev_report_date: str) -> None:
    if not prev_report_date or "שינוי דירוג" not in df.columns:
        return
    work = df[df["שינוי דירוג"].astype(str).str.match(r"↑|חדש", na=False)].copy()
    if "שינוי דירוג מספר" in work.columns:
        risers = work.sort_values("שינוי דירוג מספר", ascending=False).head(8)
    else:
        risers = work.head(8)
    fallers = df[df["שינוי דירוג"].astype(str).str.startswith("↓", na=False)].copy()
    if "שינוי דירוג מספר" in fallers.columns:
        fallers = fallers.sort_values("שינוי דירוג מספר", ascending=True).head(8)

    def _lines(sub: pd.DataFrame) -> str:
        if sub.empty:
            return "<span class='small-muted'>אין</span>"
        parts = []
        for _, r in sub.iterrows():
            sym = html.escape(str(r["סימבול"]))
            d = html.escape(str(r["שינוי דירוג"]))
            rk = html.escape(str(r.get("דירוג", "")))
            parts.append(f"<div><strong>{sym}</strong> #{rk} {_rank_delta_badge_html(d)}</div>")
        return "".join(parts)

    st.markdown(
        f"""
        <h3>שינוי דירוג מול {html.escape(prev_report_date)}</h3>
        <div class="rank-movers-grid">
            <div class="rank-mover-box"><strong>עלו בדירוג</strong><br/>{_lines(risers)}</div>
            <div class="rank-mover-box"><strong>ירדו בדירוג</strong><br/>{_lines(fallers)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_hebrew_professional_dashboard(
    df: pd.DataFrame,
    selected_date: str,
    selected_report_type: str,
    *,
    prev_report_date: str = "",
) -> None:
    strategy_state_key = f"selected_strategy_{selected_date}_{selected_report_type}"
    with st.sidebar:
        st.divider()
        _render_decision_support_panel(df, prev_report_date=prev_report_date)
        st.divider()
        _render_sidebar_section("סינון תוצאות")
        levels = list(df["רמה"].dropna().unique()) if "רמה" in df.columns else []
        selected_levels = st.multiselect("רמה", options=levels, default=levels)
        min_prob = st.slider("הסתברות מינימלית", 0, 100, 0, step=5)
        ticker_filter = st.text_input("סימבול", value="", placeholder="NVDA, AAPL…").strip().upper()

    base_filtered = df.copy()
    if selected_levels and "רמה" in base_filtered.columns:
        base_filtered = base_filtered[base_filtered["רמה"].isin(selected_levels)]
    if "הסתברות %" in base_filtered.columns:
        base_filtered = base_filtered[base_filtered["הסתברות %"] >= min_prob]
    if ticker_filter and "סימבול" in base_filtered.columns:
        base_filtered = base_filtered[base_filtered["סימבול"].astype(str).str.upper().str.contains(ticker_filter)]
    base_filtered = base_filtered.sort_values("הסתברות %", ascending=False).reset_index(drop=True)

    report_file = st.session_state.get("active_report_filename", "")
    _render_institutional_scanner_header(df, selected_date, report_file)

    if base_filtered.empty:
        st.info("אין מועמדים שעומדים בסינון הנוכחי.")
        return

    st.markdown("---")
    if prev_report_date:
        _render_rank_delta_summary(df, prev_report_date)
        st.markdown("---")
    _render_top_movers_now(base_filtered)

    st.markdown("---")
    selected_strategy = _render_strategy_breakdown(base_filtered, strategy_state_key)
    filtered = base_filtered.copy()
    if selected_strategy and "דפוס" in filtered.columns:
        filtered = filtered[filtered["דפוס"].astype(str) == selected_strategy].reset_index(drop=True)
        st.success(f"מציג עכשיו {len(filtered)} מניות מתוך {len(base_filtered)} לפי אסטרטגיה: {selected_strategy}")
    st.markdown("---")
    st.markdown('<div id="strategy-results"></div>', unsafe_allow_html=True)
    if st.session_state.pop(f"{strategy_state_key}_scroll_to_results", False):
        components.html(
            """
            <script>
            setTimeout(() => {
                const target = window.parent.document.getElementById("strategy-results");
                if (target) {
                    target.scrollIntoView({ behavior: "smooth", block: "start" });
                }
            }, 120);
            </script>
            """,
            height=0,
        )

    tab_table, tab_cards, tab_details = st.tabs([
        "טבלה מקצועית",
        "כרטיסי גרפים",
        "פרטי מניה",
    ])
    with tab_table:
        table_filtered, table_limit = _render_professional_table_filters(filtered)
        _render_dark_professional_table(table_filtered, limit=table_limit)

    with tab_cards:
        _render_chart_cards(filtered)

    with tab_details:
        symbols = filtered["סימבול"].astype(str).tolist()
        selected_symbol = st.selectbox("בחר מניה לפירוט", options=symbols)
        st.session_state["selected_ticker"] = str(selected_symbol).upper()
        st.session_state["detail_ticker"] = str(selected_symbol).upper()
        selected_row = filtered[filtered["סימבול"].astype(str) == selected_symbol].iloc[0]
        _render_symbol_details(selected_row)


def _render_professional_table_filters(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if df.empty:
        return df, 80

    st.markdown("#### סינון מהיר לטבלה המקצועית")
    st.caption("אפשר לסנן לפי טיקר, אסטרטגיה, סקטור, רמה, תג מוסדי או כל עמודה טקסטואלית אחרת.")

    work = df.copy()
    with st.expander("פתח סינונים", expanded=True):
        row1 = st.columns([1.2, 1.2, 1.2, 1.2])
        ticker_query = row1[0].text_input("טיקר", value="", placeholder="לדוגמה: NVDA, VLO", key="pro_table_ticker_filter").strip().upper()
        free_query = row1[1].text_input("חיפוש חופשי", value="", placeholder="מילה בכל הטבלה", key="pro_table_free_filter").strip()
        text_columns = [c for c in work.columns if work[c].dtype == "object" or c in ["סימבול", "סקטור", "דפוס", "רמה"]]
        selected_text_col = row1[2].selectbox("סנן לפי עמודה", options=["ללא"] + text_columns, key="pro_table_text_column_filter")
        selected_text_value = row1[3].text_input("ערך בעמודה", value="", placeholder="טקסט חלקי", key="pro_table_text_value_filter").strip()

        row2 = st.columns(4)
        selected_levels = _multiselect_existing(row2[0], work, "רמה", "רמה", "pro_table_levels")
        selected_patterns = _multiselect_existing(row2[1], work, "דפוס", "אסטרטגיה / דפוס", "pro_table_patterns")
        selected_sectors = _multiselect_existing(row2[2], work, "סקטור", "סקטור", "pro_table_sectors")
        selected_inst_tags = _multiselect_existing(row2[3], work, "תג מוסדי", "תג מוסדי", "pro_table_inst_tags")

        row3 = st.columns(5)
        min_probability = row3[0].slider("מינימום הסתברות", 0, 100, 0, 5, key="pro_table_min_probability")
        min_institutional = row3[1].slider("מינימום מוסדי", 0, 100, 0, 5, key="pro_table_min_institutional")
        min_rvol = row3[2].slider("מינימום RVOL", 0.0, 10.0, 0.0, 0.1, key="pro_table_min_rvol")
        min_change = row3[3].slider("מינימום שינוי %", -50.0, 50.0, -50.0, 0.5, key="pro_table_min_change")
        only_interesting = row3[4].checkbox("רק מעניינות", value=False, key="pro_table_only_interesting")

        row4 = st.columns([1.2, 1, 1])
        sort_options = [
            c
            for c in [
                "הסתברות %",
                "שינוי דירוג מספר",
                "ציון מוסדי",
                "ווליום יחסי",
                "שינוי %",
                "דירוג",
                "הצלחה היסטורית %",
                "ציון חדשות",
            ]
            if c in work.columns
        ]
        sort_by = row4[0].selectbox("מיין לפי", options=sort_options, index=0 if sort_options else None, key="pro_table_sort_by")
        sort_desc = row4[1].checkbox("גבוה לנמוך", value=True, key="pro_table_sort_desc")
        table_limit = row4[2].selectbox("כמה שורות להציג", options=[40, 80, 150, 300, "הכל"], index=1, key="pro_table_limit")

    if ticker_query and "סימבול" in work.columns:
        wanted = [part.strip() for part in ticker_query.split(",") if part.strip()]
        work = work[work["סימבול"].astype(str).str.upper().apply(lambda value: any(item in value for item in wanted))]
    if free_query:
        haystack = work.astype(str).agg(" ".join, axis=1)
        work = work[haystack.str.contains(free_query, case=False, na=False, regex=False)]
    if selected_text_col != "ללא" and selected_text_value:
        work = work[work[selected_text_col].astype(str).str.contains(selected_text_value, case=False, na=False, regex=False)]
    for column, selected in [
        ("רמה", selected_levels),
        ("דפוס", selected_patterns),
        ("סקטור", selected_sectors),
        ("תג מוסדי", selected_inst_tags),
    ]:
        if selected and column in work.columns:
            work = work[work[column].astype(str).isin(selected)]
    if "הסתברות %" in work.columns:
        work = work[pd.to_numeric(work["הסתברות %"], errors="coerce").fillna(0) >= min_probability]
    if "ציון מוסדי" in work.columns:
        work = work[pd.to_numeric(work["ציון מוסדי"], errors="coerce").fillna(0) >= min_institutional]
    if "ווליום יחסי" in work.columns:
        work = work[pd.to_numeric(work["ווליום יחסי"], errors="coerce").fillna(0) >= min_rvol]
    if "שינוי %" in work.columns:
        work = work[pd.to_numeric(work["שינוי %"], errors="coerce").fillna(-999) >= min_change]
    if only_interesting and "רמה" in work.columns:
        work = work[work["רמה"].isin(["A+ Setup", "Watchlist", "Early Momentum"])]
    if sort_by:
        work = work.sort_values(sort_by, ascending=not sort_desc, na_position="last")
    work = work.reset_index(drop=True)

    if work.empty:
        st.warning("אין מניות שעומדות בסינון שבחרת. נסה להרחיב תנאים.")
    else:
        st.success(f"מציג {len(work)} מתוך {len(df)} מניות לפי הסינון בטבלה.")
    return work, len(work) if table_limit == "הכל" else int(table_limit)


def _multiselect_existing(container, df: pd.DataFrame, column: str, label: str, key: str) -> list[str]:
    if column not in df.columns:
        return []
    options = sorted(
        [str(value) for value in df[column].dropna().unique() if str(value).strip()],
        key=str.casefold,
    )
    return container.multiselect(label, options=options, default=[], key=key)


def _render_dark_professional_table(df: pd.DataFrame, limit: int = 80) -> None:
    if df.empty:
        st.warning("אין שורות להצגה בטבלה.")
        return

    cols = [
        "סימבול",
        "דירוג",
        "שינוי",
        "סקטור",
        "מחיר אחרון",
        "שינוי %",
        "ווליום יחסי",
        "דפוס",
        "רמה",
        "ציון",
        "עוצמת מהלך",
        "מוסדי",
        "תג מוסדי",
        "כניסה",
        "יעד 1",
        "יעד 2",
        "סיכוי יעד 1",
        "התנגדות קרובה",
    ]
    rows_html = []
    for _, row in df.head(limit).iterrows():
        prob = int(row.get("הסתברות %", 0) or 0)
        prob_color = _probability_color(prob)
        heat = _momentum_heat(row)
        level_color = _level_color(row.get("רמה", ""))
        ticker = str(row.get("סימבול", "")).upper().strip()
        tv_url = _tradingview_url(ticker)
        rank_delta = str(row.get("שינוי דירוג", "—"))
        rows_html.append(
            "<tr>"
            f"<td><a class='ticker-link' href='{tv_url}' target='_blank' rel='noopener noreferrer'>"
            f"<span class='ticker-cell'>{_cell(ticker)}</span></a><br>"
            f"<span class='small-muted'>{_cell(row.get('מגמה'))}</span></td>"
            f"<td>{_cell(row.get('דירוג'))}</td>"
            f"<td>{_rank_delta_badge_html(rank_delta)}</td>"
            f"<td>{_cell(row.get('סקטור'))}</td>"
            f"<td>${_num(row.get('מחיר אחרון'))}</td>"
            f"<td>{_signed(row.get('שינוי %'))}%</td>"
            f"<td>{_num(row.get('ווליום יחסי'))}x</td>"
            f"<td>{_cell(row.get('דפוס'))}<br><span class='small-muted'>{_cell(row.get('מצב פריצה'))}</span></td>"
            f"<td><span class='setup-badge' style='background:{level_color};'>{_cell(row.get('רמה'))}</span></td>"
            f"<td><span class='prob-pill' style='background:{prob_color};'>{prob}%</span></td>"
            f"<td><span class='momentum-badge {heat['class']}'>{_cell(heat['label'])}</span></td>"
            f"<td>{_cell(row.get('ציון מוסדי'))}</td>"
            f"<td>{_cell(row.get('תג מוסדי'))}</td>"
            f"<td>${_num(row.get('נקודת כניסה'))}</td>"
            f"<td>${_num(row.get('יעד ראשון'))}</td>"
            f"<td>${_num(row.get('יעד שני'))}</td>"
            f"<td>{_cell(row.get('הסתברות יעד ראשון %'))}%</td>"
            f"<td>{_cell(row.get('התנגדות קרובה'))}</td>"
            "</tr>"
        )
    header = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
    body = "".join(rows_html)
    st.markdown(
        f"""
        <div class="pro-table-outer">
            <div class="pro-table-wrap">
                <table class="pro-table">
                    <thead><tr>{header}</tr></thead>
                    <tbody>{body}</tbody>
                </table>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_top_movers_now(df: pd.DataFrame) -> None:
    if df.empty or "סימבול" not in df.columns:
        return
    ranked = df.copy()
    ranked["_heat_score"] = ranked.apply(lambda row: float(_momentum_heat(row)["score"]), axis=1)
    ranked = ranked.sort_values(
        ["הסתברות %", "_heat_score", "ציון מוסדי", "ווליום יחסי"],
        ascending=[False, False, False, False],
    ).head(10)
    if ranked.empty:
        return

    st.markdown("### Top Movers Now")
    st.caption("המניות הכי חמות כרגע לפי שילוב הסתברות, ציון מוסדי, ווליום, שינוי יומי וסיכוי יעד ראשון.")
    cards_html = []
    for _, row in ranked.iterrows():
        heat = _momentum_heat(row)
        ticker = str(row.get("סימבול", "")).upper().strip()
        tv_url = _tradingview_url(ticker)
        prob = int(row.get("הסתברות %", 0) or 0)
        cards_html.append(
            f"<div class='top-mover-card {heat['card_class']}'>"
            f"<a class='ticker-link' href='{tv_url}' target='_blank' rel='noopener noreferrer'>"
            f"<div class='top-mover-symbol'>{_cell(ticker)}</div>"
            f"</a>"
            f"<div class='top-mover-score'>"
            f"<span class='momentum-badge {heat['class']}'>{_cell(heat['label'])}</span>"
            f"<span class='prob-pill' style='background:{_probability_color(prob)};'>{prob}%</span>"
            f"</div>"
            f"<div class='top-mover-meta'>"
            f"{_cell(row.get('דפוס'))}<br>"
            f"סקטור: {_cell(row.get('סקטור'))} · {_cell(row.get('דירוג סקטור'))} · שוק: {_cell(row.get('אישור שוק ללונג'))}<br>"
            f"Backtest: {_cell(row.get('הצלחה היסטורית %'))}% · חדשות: {_cell(row.get('קטליסט'))} {_cell(row.get('ציון חדשות'))}<br>"
            f"מוסדי: {_cell(row.get('ציון מוסדי'))}/100 · RVOL {_num(row.get('ווליום יחסי'))}x<br>"
            f"כניסה: ${_num(row.get('נקודת כניסה'))} · יעד 1: ${_num(row.get('יעד ראשון'))}"
            f"</div>"
            f"</div>"
        )
    st.markdown(
        f"<div class='top-movers-grid'>{''.join(cards_html)}</div>",
        unsafe_allow_html=True,
    )


def _sparkline_svg(values) -> str:
    if not isinstance(values, list) or len(values) < 2:
        return "<span class='small-muted'>אין גרף</span>"
    nums = [float(v) for v in values if pd.notna(v)]
    if len(nums) < 2:
        return "<span class='small-muted'>אין גרף</span>"
    width, height, pad = 130, 42, 4
    lo, hi = min(nums), max(nums)
    span = hi - lo or 1.0
    points = []
    for i, value in enumerate(nums):
        x = pad + i * (width - 2 * pad) / (len(nums) - 1)
        y = height - pad - (value - lo) / span * (height - 2 * pad)
        points.append(f"{x:.1f},{y:.1f}")
    color = "#22c55e" if nums[-1] >= nums[0] else "#ef4444"
    return (
        f"<svg width='{width}' height='{height}' viewBox='0 0 {width} {height}' "
        f"style='background:#020617;border-radius:8px;border:1px solid rgba(96,165,250,.22)'>"
        f"<polyline fill='none' stroke='{color}' stroke-width='2.4' points='{' '.join(points)}'/>"
        f"<circle cx='{points[-1].split(',')[0]}' cy='{points[-1].split(',')[1]}' r='3' fill='{color}'/>"
        "</svg>"
    )


def _probability_color(probability: int) -> str:
    if probability >= 80:
        return "linear-gradient(135deg,#16a34a,#22c55e)"
    if probability >= 60:
        return "linear-gradient(135deg,#ca8a04,#eab308)"
    if probability >= 45:
        return "linear-gradient(135deg,#0891b2,#06b6d4)"
    return "linear-gradient(135deg,#475569,#64748b)"


def _momentum_heat(row: pd.Series) -> dict[str, str]:
    prob = _float_or_none(row.get("הסתברות %")) or 0
    inst = _float_or_none(row.get("ציון מוסדי")) or 0
    rvol = _float_or_none(row.get("ווליום יחסי")) or 0
    change = _float_or_none(row.get("שינוי %")) or 0
    target_prob = _float_or_none(row.get("הסתברות יעד ראשון %")) or prob

    heat_score = 0.42 * prob + 0.34 * inst + min(rvol, 3.0) * 6 + max(min(change, 8), -4) * 1.6
    heat_score = max(0, min(100, heat_score))
    if prob >= 95 and inst >= 82 and rvol >= 1.3 and target_prob >= 80:
        return {"label": "עילית לעוף", "class": "heat-elite", "card_class": "heatbar-elite", "score": f"{heat_score:.2f}"}
    if heat_score >= 82:
        return {"label": "חם מאוד", "class": "heat-hot", "card_class": "heatbar-hot", "score": f"{heat_score:.2f}"}
    if heat_score >= 68:
        return {"label": "חזק", "class": "heat-strong", "card_class": "heatbar-strong", "score": f"{heat_score:.2f}"}
    return {"label": "מעקב", "class": "heat-watch", "card_class": "heatbar-watch", "score": f"{heat_score:.2f}"}


def _tradingview_url(symbol: str) -> str:
    clean_symbol = str(symbol).upper().strip().replace(".", "-")
    return f"https://www.tradingview.com/chart/?symbol={quote(clean_symbol)}"


def _cell(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return html.escape(str(value))


def _num(value) -> str:
    try:
        if pd.isna(value):
            return "-"
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return _cell(value)


def _signed(value) -> str:
    try:
        if pd.isna(value):
            return "-"
        return f"{float(value):+.2f}"
    except (TypeError, ValueError):
        return _cell(value)


def _render_chart_cards(df: pd.DataFrame) -> None:
    st.caption("כרטיסי הגרף הם Preview של תנועת המחיר והטריגר. שעתי מוצג רק למניות Top 50 שקיבלו דאטה intraday.")
    controls = st.columns([1, 1, 2])
    timeframe_options = ["יומי", "שבועי"]
    if "גרף שעתי" in df.columns and df["גרף שעתי"].apply(lambda values: isinstance(values, list) and len(values) > 1).any():
        timeframe_options.append("שעתי")
    timeframe = controls[0].radio("טווח גרף", timeframe_options, horizontal=True)
    count_choice = controls[1].selectbox("כמה כרטיסים", ["20", "50", "100", "כל המסוננים"], index=0)
    chart_col = {
        "שעתי": "גרף שעתי",
        "שבועי": "גרף שבועי",
        "יומי": "גרף יומי",
    }.get(timeframe, "גרף יומי")
    if chart_col not in df.columns:
        chart_col = "גרף קטן"
    if count_choice == "כל המסוננים":
        limit = len(df)
        controls[2].warning("הצגת כל הכרטיסים יכולה להיות כבדה אם יש הרבה מניות.")
    else:
        limit = min(int(count_choice), len(df))
        controls[2].info(f"מוצגים {limit} מתוך {len(df)} כרטיסים מסוננים.")

    work = df.copy()
    if "הסתברות %" in work.columns:
        work = work.sort_values("הסתברות %", ascending=False)
    top = work.head(limit).reset_index(drop=True)
    for start in range(0, len(top), 2):
        cols = st.columns(2)
        for col, (_, row) in zip(cols, top.iloc[start:start + 2].iterrows()):
            with col:
                color = _level_color(row.get("רמה", ""))
                heat = _momentum_heat(row)
                ticker = str(row["סימבול"]).upper().strip()
                tv_url = _tradingview_url(ticker)
                gf_url = html.escape(_google_finance_url(ticker))
                level = str(row.get("רמה", ""))
                level_skin = {
                    "A+ Setup": "chart-card-aplus",
                    "Watchlist": "chart-card-watch",
                }.get(level, "")
                prob = int(row.get("הסתברות %", 0) or 0)
                st.markdown(
                    f"""
                    <div class="chart-card-premium momentum-card {heat['card_class']} {level_skin}">
                        <div class="chart-card-head">
                            <a class="ticker-link chart-card-symbol" href="{tv_url}" target="_blank" rel="noopener">{_cell(ticker)}</a>
                            <div class="chart-card-metrics">
                                <span class="prob-pill" style="background:{_probability_color(prob)};">{prob}%</span>
                                <span class="setup-badge" style="background:{color};">{_cell(level)}</span>
                                <span class="momentum-badge {heat['class']}">{_cell(heat['label'])}</span>
                            </div>
                        </div>
                        <div class="chart-card-meta">
                            {timeframe} · {_cell(row.get('דפוס'))} · RVOL {_num(row.get('ווליום יחסי'))}x<br/>
                            {_cell(row.get('מצב פריצה'))} · כניסה ${_num(row.get('נקודת כניסה'))} · יעד ${_num(row.get('יעד ראשון'))}<br/>
                            <a class="ticker-link" href="{gf_url}" target="_blank" rel="noopener">Google Finance ↗</a>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                _render_tradingview_style_chart(
                    row[chart_col],
                    height=260,
                    breakout_level=row.get("נקודת כניסה"),
                )


def _render_strategy_breakdown(df: pd.DataFrame, state_key: str) -> str | None:
    required = {"דפוס", "רמה", "הסתברות %", "ווליום יחסי", "שינוי %", "סימבול"}
    if df.empty or not required.issubset(df.columns):
        st.info("אין מספיק נתונים לחישוב אסטרטגיות.")
        return None

    positive_levels = {"A+ Setup", "Watchlist", "Early Momentum"}
    work = df[df["רמה"].isin(positive_levels)].copy()
    if work.empty:
        st.info("אין כרגע אסטרטגיות חיוביות לפי הסינון הנוכחי.")
        return None

    st.markdown("### אסטרטגיות עם הסיכוי האיכותי ביותר כרגע")
    st.caption("לחיצה על כרטיס אסטרטגיה מסננת את הטבלה והגרפים למטה. זה כלי ניווט ודירוג, לא הבטחה לטרייד.")

    summary_rows = []
    for pattern, group in work.groupby("דפוס", dropna=False):
        ranked = group.sort_values(
            [c for c in ["הסתברות %", "ציון מוסדי", "סיכוי למהלך %", "ווליום יחסי"] if c in group.columns],
            ascending=False,
        )
        summary_rows.append({
            "אסטרטגיה": str(pattern),
            "סה״כ מועמדים": len(group),
            "A+": int((group["רמה"] == "A+ Setup").sum()),
            "ציון ממוצע": round(float(group["הסתברות %"].mean()), 1),
            "ציון מוסדי ממוצע": round(float(group["ציון מוסדי"].mean()), 1) if "ציון מוסדי" in group.columns else 0,
            "RVOL ממוצע": round(float(group["ווליום יחסי"].mean()), 2),
            "שינוי ממוצע %": round(float(group["שינוי %"].mean()), 2),
            "מניות מובילות": ", ".join(ranked["סימבול"].astype(str).head(8).tolist()),
        })

    summary = pd.DataFrame(summary_rows)
    summary = summary.sort_values(
        ["A+", "ציון ממוצע", "ציון מוסדי ממוצע", "RVOL ממוצע"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)
    summary.insert(0, "דירוג", range(1, len(summary) + 1))

    valid_patterns = set(summary["אסטרטגיה"].astype(str))
    if state_key not in st.session_state or st.session_state[state_key] not in valid_patterns:
        st.session_state[state_key] = None

    top = summary.iloc[0]
    selected_label = st.session_state[state_key] or "כל הרשימה"
    st.markdown(
        f"""
        <div class="strategy-summary-grid">
            <div class="strategy-summary-card">
                <div class="label">אסטרטגיה מובילה</div>
                <div class="value">{_cell(top["אסטרטגיה"])}</div>
            </div>
            <div class="strategy-summary-card">
                <div class="label">A+ באסטרטגיה</div>
                <div class="value">{int(top["A+"])}</div>
            </div>
            <div class="strategy-summary-card">
                <div class="label">ציון מוסדי ממוצע</div>
                <div class="value">{float(top["ציון מוסדי ממוצע"]):.1f}/100</div>
            </div>
            <div class="strategy-summary-card">
                <div class="label">סינון פעיל</div>
                <div class="value">{_cell(selected_label)}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="strategy-reset-card">
            <div class="strategy-reset-title">כל האסטרטגיות</div>
            <div class="strategy-reset-subtitle">חזרה לרשימה המלאה בלי סינון לפי דפוס.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("הצג את כל האסטרטגיות", key=f"{state_key}_all", use_container_width=True):
        st.session_state[state_key] = None
        st.session_state[f"{state_key}_scroll_to_results"] = True

    cards = summary.head(8)
    for start in range(0, len(cards), 4):
        cols = st.columns(4)
        for col, (_, row) in zip(cols, cards.iloc[start:start + 4].iterrows()):
            pattern = str(row["אסטרטגיה"])
            is_active = st.session_state[state_key] == pattern
            active_class = " active" if is_active else ""
            with col:
                st.markdown(
                    f"""
                    <div class="strategy-card{active_class}">
                        <div class="strategy-title">{_cell(pattern)}</div>
                        <div class="strategy-stats">
                            <div class="strategy-stat"><span>מועמדים</span><strong>{int(row['סה״כ מועמדים'])}</strong></div>
                            <div class="strategy-stat"><span>A+</span><strong>{int(row['A+'])}</strong></div>
                            <div class="strategy-stat"><span>מוסדי</span><strong>{float(row['ציון מוסדי ממוצע']):.0f}</strong></div>
                        </div>
                        <div class="strategy-tickers">{_cell(row['מניות מובילות'])}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if st.button(
                    "פתח אסטרטגיה" if not is_active else "אסטרטגיה פתוחה",
                    key=f"{state_key}_{row['דירוג']}",
                    use_container_width=True,
                ):
                    st.session_state[state_key] = None if is_active else pattern
                    st.session_state[f"{state_key}_scroll_to_results"] = True

    with st.expander("טבלת סיכום אסטרטגיות מלאה", expanded=False):
        st.dataframe(
            summary,
            use_container_width=True,
            hide_index=True,
            column_config={
                "ציון ממוצע": st.column_config.ProgressColumn(
                    "ציון ממוצע",
                    min_value=0,
                    max_value=100,
                    format="%.1f",
                ),
                "ציון מוסדי ממוצע": st.column_config.ProgressColumn(
                    "ציון מוסדי ממוצע",
                    min_value=0,
                    max_value=100,
                    format="%.1f",
                ),
                "RVOL ממוצע": st.column_config.NumberColumn(format="%.2fx"),
                "שינוי ממוצע %": st.column_config.NumberColumn(format="%+.2f%%"),
            },
        )

    return st.session_state[state_key]


def _render_symbol_details(row: pd.Series) -> None:
    color = _level_color(row.get("רמה", ""))
    heat = _momentum_heat(row)
    ticker = str(row["סימבול"]).upper().strip()
    st.session_state["last_ticker"] = ticker
    tv_url = _tradingview_url(ticker)
    st.markdown(
        f"""
        <div class="setup-card momentum-card {heat['card_class']}">
            <div class="setup-symbol">
                <a class="ticker-link" href="{tv_url}" target="_blank" rel="noopener noreferrer">{_cell(ticker)}</a>
            </div>
            <span class="setup-badge" style="background:{color};">
                {row['רמה']} · ציון איכות {int(row['הסתברות %'])}/100
            </span>
            <span class="momentum-badge {heat['class']}">{_cell(heat['label'])}</span>
            <div class="setup-text">{row['הסבר']}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if "שינוי דירוג" in row.index:
        c_rank = st.columns(3)
        c_rank[0].metric("דירוג היום", str(row.get("דירוג", "—")))
        c_rank[1].metric("דירוג אתמול", str(row.get("דירוג אתמול", "—")) or "—")
        c_rank[2].markdown(f"**שינוי:** {_rank_delta_badge_html(str(row.get('שינוי דירוג', '—')))}", unsafe_allow_html=True)
    st.markdown("#### יעוץ לפי הנתונים")
    _render_ticker_advice_card(row)
    st.link_button("פתח גרף ב-TradingView", tv_url, use_container_width=True)
    _render_tradingview_style_chart(row["גרף קטן"], height=320)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("RSI", _format_metric(row.get("RSI")))
    c2.metric("MACD", str(row.get("MACD", "")))
    c3.metric("ADX", _format_metric(row.get("ADX")))
    c4.metric("CCI", _format_metric(row.get("CCI")))

    st.markdown("#### שכבת אישור מוסדי")
    inst_cols = st.columns(4)
    inst_cols[0].metric("ציון מוסדי", f"{int(row.get('ציון מוסדי', 0) or 0)}/100")
    inst_cols[1].metric("תג מוסדי", str(row.get("תג מוסדי", "")))
    inst_cols[2].metric("RS מול SPY", _pct_metric(row.get("חוזק יחסי SPY 20 יום %")))
    inst_cols[3].metric("RS מול QQQ", _pct_metric(row.get("חוזק יחסי QQQ 20 יום %")))
    inst_cols2 = st.columns(2)
    inst_cols2[0].metric("איכות נר", str(row.get("איכות נר", "")))
    inst_cols2[1].metric("אישור ווליום", str(row.get("אישור ווליום", "")))
    if "הערת מוסדיים" in row:
        st.caption(_markdown_text(row.get("הערת מוסדיים", "")))

    st.markdown("#### מצב שוק וסקטור")
    market_cols = st.columns(4)
    market_cols[0].metric("סקטור", str(row.get("סקטור", "לא זמין")))
    market_cols[1].metric("מצב שוק", str(row.get("מצב שוק", "לא זמין")))
    market_cols[2].metric("ציון שוק", f"{int(row.get('ציון שוק', 0) or 0)}/100")
    market_cols[3].metric("אישור שוק ללונג", str(row.get("אישור שוק ללונג", "לא נבדק")))
    if "הערת שוק" in row:
        st.caption(_markdown_text(row.get("הערת שוק", "")))
    sector_cols = st.columns(3)
    sector_cols[0].metric("ציון סקטור", f"{int(row.get('ציון סקטור', 0) or 0)}/100")
    sector_cols[1].metric("חוזק סקטור 20 יום", _pct_metric(row.get("חוזק סקטור 20 יום %")))
    sector_cols[2].metric("דירוג סקטור", str(row.get("דירוג סקטור", "לא זמין")))
    if "הערת סקטור" in row:
        st.caption(_markdown_text(row.get("הערת סקטור", "")))

    st.markdown("#### Backtest וחדשות")
    edge_cols = st.columns(4)
    edge_cols[0].metric("הצלחה היסטורית", _pct_metric(row.get("הצלחה היסטורית %")))
    edge_cols[1].metric("דגימות", _format_metric(row.get("דגימות היסטוריות")))
    edge_cols[2].metric("תנועה היסטורית ממוצעת", _pct_metric(row.get("תשואה היסטורית ממוצעת %")))
    edge_cols[3].metric("ציון חדשות", _format_metric(row.get("ציון חדשות")))
    if "הערת Backtest" in row:
        st.caption(_markdown_text(row.get("הערת Backtest", "")))
    if str(row.get("חדשות אחרונות", "")).strip():
        st.write(f"**קטליסט:** {_markdown_text(row.get('קטליסט', ''))}")
        st.write(f"**חדשות אחרונות:** {_markdown_text(row.get('חדשות אחרונות', ''))}")
        st.caption(f"תאריך חדשות: {row.get('תאריך חדשות', '')}")

    st.markdown("#### טכני מורחב")
    tech_cols = st.columns(4)
    tech_cols[0].metric("SMA20", _money_metric(row.get("SMA20")))
    tech_cols[1].metric("SMA50", _money_metric(row.get("SMA50")))
    tech_cols[2].metric("SMA200", _money_metric(row.get("SMA200")))
    tech_cols[3].metric("ATR14", _format_metric(row.get("ATR14")))
    tech_cols2 = st.columns(4)
    tech_cols2[0].metric("מרחק SMA20", _pct_metric(row.get("מרחק מ-SMA20 %")))
    tech_cols2[1].metric("מרחק SMA50", _pct_metric(row.get("מרחק מ-SMA50 %")))
    tech_cols2[2].metric("מרחק פריצת 20 יום", _pct_metric(row.get("מרחק מפריצת 20 יום %")))
    tech_cols2[3].metric("מרחק פריצת 50 יום", _pct_metric(row.get("מרחק מפריצת 50 יום %")))

    st.markdown("#### שורט / סקוויז")
    short_cols = st.columns(3)
    short_cols[0].metric("שורט אינטרסט", str(row.get("שורט אינטרסט", "לא זמין")))
    short_cols[1].metric("שורט פלואט %", str(row.get("שורט פלואט %", "לא זמין")))
    short_cols[2].metric("שורט חריג", str(row.get("שורט חריג", "לא זמין")))
    st.caption("הערה: Short interest דורש מקור דאטה ייעודי. אם Polygon לא מספק את זה במסלול הנוכחי, המערכת לא ממציאה נתון.")

    st.markdown("#### תוכנית פעולה")
    st.write(f"**נקודת כניסה:** `{row['נקודת כניסה']}`")
    st.write(f"**סטופ / ביטול:** {row['סטופ / ביטול']}")
    st.write(f"**יעד ראשון:** `{row['יעד ראשון']}`")
    if "יעד שני" in row:
        st.write(f"**יעד שני:** `{row['יעד שני']}`")
    if "התנגדות קרובה" in row:
        st.write(f"**התנגדות קרובה:** {_markdown_text(row['התנגדות קרובה'])}")
    if "מימוש רווח" in row:
        st.write(f"**מימוש רווח:** {_markdown_text(row['מימוש רווח'])}")
    prob_cols = st.columns(3)
    if "הסתברות יעד ראשון %" in row:
        prob_cols[0].metric("הסתברות יעד 1", f"{int(row.get('הסתברות יעד ראשון %', 0) or 0)}%")
    if "הסתברות יעד שני %" in row:
        prob_cols[1].metric("הסתברות יעד 2", f"{int(row.get('הסתברות יעד שני %', 0) or 0)}%")
    if "זמן משוער ליעדים" in row:
        prob_cols[2].metric("זמן משוער", str(row.get("זמן משוער ליעדים", "-")))
    st.write(f"**מה לחכות:** {row['מה לחכות']}")
    st.write(f"**סיכון:** {row['הערת סיכון']}")


def _format_metric(value) -> str:
    try:
        if pd.isna(value):
            return "-"
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return str(value)


def _markdown_text(value) -> str:
    return str(value).replace("$", "\\$")


def _money_metric(value) -> str:
    try:
        if pd.isna(value):
            return "-"
        return f"${float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _pct_metric(value) -> str:
    try:
        if pd.isna(value):
            return "-"
        return f"{float(value):+.2f}%"
    except (TypeError, ValueError):
        return str(value)


def _float_or_none(value) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _render_tradingview_style_chart(values, height: int = 180, breakout_level=None) -> None:
    if not isinstance(values, list) or len(values) < 2:
        st.info("אין מספיק דאטה לגרף.")
        return
    chart_df = pd.DataFrame({
        "bar": list(range(len(values))),
        "price": [float(v) for v in values],
    })
    min_price = chart_df["price"].min()
    max_price = chart_df["price"].max()
    breakout_value = _float_or_none(breakout_level)
    if breakout_value is not None:
        min_price = min(min_price, breakout_value)
        max_price = max(max_price, breakout_value)
    padding = max((max_price - min_price) * 0.08, max_price * 0.003, 0.5)
    domain_floor = max(0.01, min_price - padding)
    domain_ceiling = max_price + padding
    up = chart_df["price"].iloc[-1] >= chart_df["price"].iloc[0]
    line_color = "#22c55e" if up else "#ef4444"
    area_color = "#16a34a" if up else "#dc2626"

    base = alt.Chart(chart_df).encode(
        x=alt.X("bar:Q", axis=None),
        y=alt.Y(
            "price:Q",
            scale=alt.Scale(domain=[domain_floor, domain_ceiling], zero=False),
            axis=alt.Axis(
                orient="right",
                labelColor="#cbd5e1",
                gridColor="rgba(148,163,184,0.12)",
                tickColor="rgba(148,163,184,0.25)",
            ),
        ),
    )
    baseline = alt.Chart(pd.DataFrame({
        "bar": [chart_df["bar"].min(), chart_df["bar"].max()],
        "price": [chart_df["price"].iloc[-1], chart_df["price"].iloc[-1]],
    })).mark_line(
        color="rgba(148,163,184,0.35)",
        strokeDash=[5, 5],
        strokeWidth=1,
    ).encode(x="bar:Q", y="price:Q")
    area = base.mark_area(
        line=False,
        opacity=0.32,
        color=area_color,
        interpolate="monotone",
    ).encode(y2=alt.Y2(datum=domain_floor))
    glow = base.mark_line(
        color=line_color,
        strokeWidth=7,
        opacity=0.16,
        interpolate="monotone",
    )
    line = base.mark_line(
        color=line_color,
        strokeWidth=3.2,
        interpolate="monotone",
    )
    last_point = alt.Chart(chart_df.tail(1)).mark_circle(
        color=line_color,
        size=70,
        stroke="#e0f2fe",
        strokeWidth=1.4,
    ).encode(x="bar:Q", y="price:Q")
    layers = [area, glow, line, baseline]
    if breakout_value is not None:
        breakout_line = alt.Chart(pd.DataFrame({
            "bar": [chart_df["bar"].min(), chart_df["bar"].max()],
            "price": [breakout_value, breakout_value],
        })).mark_line(
            color="#f59e0b",
            strokeDash=[7, 5],
            strokeWidth=2,
        ).encode(x="bar:Q", y="price:Q")
        layers.append(breakout_line)
    layers.append(last_point)

    chart = alt.layer(*layers).properties(
        height=height,
        background="#020617",
    ).configure_view(
        stroke="rgba(96,165,250,0.24)",
    )
    st.markdown('<div class="chart-frame">', unsafe_allow_html=True)
    st.altair_chart(chart, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
