"""
Apex Momentum Scanner — professional dashboard (Trade Ideas / institutional style).
"""

from __future__ import annotations

import hmac
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.env_secrets import clean_env_secret
from src.report_persistence import last_report_path, load_last_report, save_last_report
from src.report_paths import is_official_report_csv

REPORTS_DIR = ROOT / "data" / "reports"
BRAND = "Apex Momentum"
SCANNER_SCRIPT = "scripts/run_apex_scanner.py"


def _is_cloud() -> bool:
    return os.getenv("RENDER", "").lower() in {"1", "true", "yes", "on"} or bool(os.getenv("SPACE_ID"))


def _provider() -> str:
    from src.polygon_key_store import resolve_polygon_api_key

    if resolve_polygon_api_key():
        return "polygon"
    return os.getenv("DATA_PROVIDER", "polygon").strip().lower()


def _render_polygon_setup() -> None:
    from src.polygon_key_store import (
        polygon_key_source,
        polygon_key_tail,
        resolve_polygon_api_key,
        save_polygon_api_key,
    )

    st.sidebar.markdown("### 🔑 נתוני שוק (Polygon)")
    key = resolve_polygon_api_key()
    if key:
        st.sidebar.success(f"מחובר · מקור: {polygon_key_source()} · …{polygon_key_tail(key)}")
        st.sidebar.caption("מחירים אמיתיים מ-Polygon (מותאמים לספליטים)")
    else:
        st.sidebar.error("אין מפתח Polygon — הסריקה לא תציג מחירי שוק אמיתיים")
        pasted = st.sidebar.text_input("הדבק מפתח Polygon", type="password", key="apex_polygon_paste")
        if st.sidebar.button("שמור מפתח", use_container_width=True):
            try:
                save_polygon_api_key(pasted)
                st.sidebar.success("המפתח נשמר — הרץ סריקה מחדש")
                st.rerun()
            except ValueError as exc:
                st.sidebar.error(str(exc))
        st.sidebar.caption(
            "או ב-Render: Environment → `POLYGON_API_KEY` + `DATA_PROVIDER=polygon` → Deploy"
        )


def _require_password() -> None:
    password = clean_env_secret(os.getenv("DASHBOARD_PASSWORD", ""))
    if not password or st.session_state.get("dashboard_authenticated"):
        return
    st.markdown(f"### 🔐 {BRAND}")
    st.caption("כניסה מאובטחת — הגדר `DASHBOARD_PASSWORD` ב-Render")
    entered = st.text_input("סיסמה", type="password")
    if st.button("כניסה", type="primary"):
        if entered.strip() and hmac.compare_digest(
            entered.strip().encode("utf-8"),
            password.encode("utf-8"),
        ):
            st.session_state["dashboard_authenticated"] = True
            st.rerun()
        else:
            st.error("סיסמה שגויה")
    st.stop()


st.set_page_config(
    page_title=f"{BRAND} | Institutional Scanner",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600;700&display=swap');
        html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
        .stApp { background: linear-gradient(165deg, #030712 0%, #0f172a 45%, #020617 100%); }
        .apex-hero {
            background: linear-gradient(90deg, rgba(234,179,8,0.12), rgba(59,130,246,0.08));
            border: 1px solid rgba(234,179,8,0.35);
            border-radius: 12px;
            padding: 1rem 1.25rem;
            margin-bottom: 1rem;
        }
        .apex-hero h1 { color: #fbbf24; margin: 0; font-size: 1.6rem; }
        .apex-hero p { color: #94a3b8; margin: 0.35rem 0 0; font-size: 0.95rem; }
        div[data-testid="stMetric"] {
            background: rgba(15,23,42,0.85);
            border: 1px solid rgba(51,65,85,0.8);
            border-radius: 10px;
            padding: 0.5rem;
        }
        div[data-testid="stMetric"] label { color: #94a3b8 !important; }
        div[data-testid="stMetric"] div[data-testid="stMetricValue"] { color: #f1f5f9 !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _discover_reports() -> list[Path]:
    if not REPORTS_DIR.exists():
        return []
    files = [p for p in REPORTS_DIR.glob("*_report.csv") if is_official_report_csv(p.name)]
    apex_first = sorted(files, key=lambda p: ("apex" not in p.name.lower(), -p.stat().st_mtime))
    return apex_first


def _parse_chart(cell) -> list[dict]:
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return []
    if isinstance(cell, list):
        return cell
    try:
        return json.loads(str(cell))
    except (json.JSONDecodeError, TypeError):
        return []


@st.cache_data(show_spinner=False)
def load_report(path_str: str, mtime: float) -> pd.DataFrame:
    _ = mtime
    p = Path(path_str)
    if not p.is_file() or p.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(p)


def _plot_candlestick(bars: list[dict], symbol: str, entry: float | None, stop: float | None) -> None:
    if len(bars) < 5:
        st.info("אין מספיק נתונים לגרף.")
        return
    df = pd.DataFrame(bars)
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.72, 0.28],
    )
    fig.add_trace(
        go.Candlestick(
            x=df["d"],
            open=df["o"],
            high=df["h"],
            low=df["l"],
            close=df["c"],
            name=symbol,
            increasing_line_color="#22c55e",
            decreasing_line_color="#ef4444",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(x=df["d"], y=df["v"], name="Volume", marker_color="rgba(59,130,246,0.45)"),
        row=2,
        col=1,
    )
    if entry:
        fig.add_hline(y=entry, line_dash="dash", line_color="#fbbf24", row=1, col=1)
    if stop:
        fig.add_hline(y=stop, line_dash="dot", line_color="#ef4444", row=1, col=1)
    fig.update_layout(
        template="plotly_dark",
        height=480,
        margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#0f172a",
        xaxis_rangeslider_visible=False,
        showlegend=False,
        title=dict(text=f"{symbol} — Daily", font=dict(color="#e2e8f0")),
    )
    fig.update_xaxes(gridcolor="rgba(148,163,184,0.1)")
    fig.update_yaxes(gridcolor="rgba(148,163,184,0.1)")
    st.plotly_chart(fig, use_container_width=True)


def _score_color(val: float) -> str:
    if val >= 85:
        return "background-color:#14532d;color:#bbf7d0"
    if val >= 70:
        return "background-color:#422006;color:#fde68a"
    return "background-color:#1e293b;color:#cbd5e1"


def _styled_table(df: pd.DataFrame) -> None:
    show = df.copy()
    for col in ("chart_json",):
        if col in show.columns:
            show = show.drop(columns=[col])
    if "Apex Score" in show.columns:
        styled = show.style.map(
            lambda v: _score_color(float(v)) if pd.notna(v) else "",
            subset=["Apex Score"],
        )
        st.dataframe(styled, use_container_width=True, height=520)
    else:
        st.dataframe(show, use_container_width=True, height=520)


def _run_scan_subprocess() -> tuple[bool, str]:
    import subprocess

    cmd = [
        sys.executable,
        str(ROOT / SCANNER_SCRIPT),
        "--universe-csv",
        str(ROOT / "data/universe/polygon_liquid_us.csv"),
        "--sector-map",
        str(ROOT / "data/universe/sector_map.csv"),
        "--output-suffix",
        "apex",
        "--no-charts",
    ]
    if _is_cloud():
        from src.scan_runtime import cap_scan_workers

        cmd.extend(["--workers", str(cap_scan_workers(8))])
    timeout = int(os.getenv("SCAN_TIMEOUT_SECONDS", "900") or "900")
    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "Timeout — נסה שוב או השתמש ברמת דמו."
    out = "\n".join(p for p in (proc.stdout, proc.stderr) if p)
    return proc.returncode == 0, out[-4000:]


def _cloud_scan_ui() -> None:
    try:
        from src.cloud_scan_job import cancel_scan, get_status, start_full_scan
    except ImportError:
        return

    st.sidebar.markdown("### ▶ סריקה")
    state = get_status().get("state", "idle")
    if state == "running":
        from src.cloud_scan_job import get_scan_progress

        prog = get_scan_progress()
        st.sidebar.progress(min(100, int(prog.get("percent", 0))) / 100.0)
        st.sidebar.caption(prog.get("message", "רץ…"))
        if st.sidebar.button("⏹ בטל"):
            cancel_scan()
            st.rerun()
    else:
        if st.sidebar.button("▶ הרץ Apex Scan", type="primary", use_container_width=True):
            os.environ["SCAN_ENGINE"] = "apex"
            started, msg = start_full_scan("simple")
            if started:
                st.sidebar.success(msg)
            else:
                st.sidebar.warning(msg)
            st.rerun()


def main() -> None:
    _require_password()
    _css()
    st.markdown(
        f"""
        <div class="apex-hero">
            <h1>⚡ {BRAND}</h1>
            <p>סורק מומנטום מוסדי · RS Rating · דפוסי פריצה · תוכנית מסחר</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _render_polygon_setup()

    if _provider() == "demo":
        st.warning(
            "**מצב דמו** — מחירים מדומים בלבד. להפעלת שוק אמיתי הזן מפתח Polygon בסרגל."
        )
    elif _provider() == "polygon":
        st.success("**נתוני שוק אמיתיים** — Polygon (מחירים מותאמים, ~2,114 מניות נזילות US)")

    _cloud_scan_ui()

    reports = _discover_reports()
    if not reports:
        st.info("אין דוח. לחץ **הרץ Apex Scan** בסרגל או הרץ: `python scripts/run_apex_scanner.py`")
        if st.button("הרץ סריקה מקומית (דמו)", type="primary"):
            with st.spinner("סורק…"):
                ok, log = _run_scan_subprocess()
            if ok:
                st.success("הסתיים")
                st.rerun()
            else:
                st.code(log)
        return

    with st.sidebar:
        st.markdown("### דוח")
        labels = [p.name for p in reports]
        pick = st.selectbox("קובץ", labels, index=0)
        path = reports[labels.index(pick)]
        mtime = datetime.fromtimestamp(path.stat().st_mtime).strftime("%d/%m %H:%M")

    df = load_report(str(path), path.stat().st_mtime)
    if df.empty:
        st.warning("דוח ריק")
        return

    is_apex = "Apex Score" in df.columns
    if not is_apex:
        st.error("דוח זה מהסורק הישן. הרץ **Apex Scan** לדוח חדש.")
        return

    st.sidebar.caption(f"עודכן: {mtime} · {len(df):,} שורות")

    min_score = st.sidebar.slider("מינימום Apex Score", 0, 100, 55)
    min_rs = st.sidebar.slider("מינימום RS Rating", 0, 99, 50)
    setups = ["הכל"] + sorted(df["דפוס"].dropna().unique().tolist())
    setup_pick = st.sidebar.selectbox("דפוס", setups)

    filt = df[(df["Apex Score"] >= min_score) & (df["RS Rating"] >= min_rs)]
    if setup_pick != "הכל":
        filt = filt[filt["דפוס"] == setup_pick]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("מניות בפילטר", f"{len(filt):,}")
    c2.metric("Apex 80+", int((filt["Apex Score"] >= 80).sum()))
    c3.metric("RS 80+", int((filt["RS Rating"] >= 80).sum()))
    if len(filt):
        c4.metric("מוביל", str(filt.iloc[0]["סימבול"]))
    else:
        c4.metric("מוביל", "—")

    from dashboard.apex_live_ui import render_alerts_tab, render_live_tab, render_presets_tab

    tab_table, tab_live, tab_presets, tab_alerts, tab_chart, tab_sectors = st.tabs(
        ["📊 יומי", "⚡ Live", "📋 Presets", "🔔 התראות", "📈 גרף", "🏭 סקטורים"]
    )

    with tab_table:
        _styled_table(filt.head(200))

    with tab_live:
        render_live_tab(df)

    with tab_presets:
        render_presets_tab(df)

    with tab_alerts:
        render_alerts_tab()

    with tab_chart:
        symbols = filt["סימבול"].astype(str).tolist()[:300]
        if not symbols:
            st.info("אין מניות בפילטר")
        else:
            sym = st.selectbox("בחר מניה", symbols, key="apex_chart_sym")
            row = filt[filt["סימבול"].astype(str) == sym].iloc[0]
            bars = _parse_chart(row.get("chart_json"))
            entry = float(row["כניסה"]) if pd.notna(row.get("כניסה")) else None
            stop = float(row["סטופ"]) if pd.notna(row.get("סטופ")) else None
            _plot_candlestick(bars, sym, entry, stop)
            st.markdown(f"**{row['סיכום']}**")
            st.caption(f"טריגר: {row.get('טריגר', '')} · R:R {row.get('R:R', '')}")

    with tab_sectors:
        if "סקטור" in filt.columns and len(filt):
            sec = (
                filt.groupby("סקטור")
                .agg(count=("סימבול", "count"), avg_score=("Apex Score", "mean"), avg_rs=("RS Rating", "mean"))
                .sort_values("avg_score", ascending=False)
                .head(25)
            )
            st.dataframe(sec.round(1), use_container_width=True)
        else:
            st.info("אין נתוני סקטור")

    save_last_report(path.name, "apex")


if __name__ == "__main__":
    main()
