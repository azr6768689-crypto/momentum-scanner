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


def _render_polygon_key_form(label_prefix: str = "") -> None:
    """Paste / test / save Polygon API key. Shared by both initial setup
    and the 'replace key' flow when an existing key was rejected (401)."""
    from src.polygon_key_store import polygon_key_tail, save_polygon_api_key

    key_id = f"apex_polygon_paste_{label_prefix or 'init'}"
    pasted = st.sidebar.text_input("הדבק מפתח Polygon", type="password", key=key_id)
    c_test, c_save = st.sidebar.columns(2)
    with c_test:
        if st.button("בדוק", use_container_width=True, key=f"{key_id}_test") and pasted.strip():
            from src.polygon_preflight import validate_polygon_api_key

            ok, msg = validate_polygon_api_key(pasted.strip())
            if ok:
                st.sidebar.success(f"✅ מפתח תקין · …{polygon_key_tail(pasted)}")
            else:
                st.sidebar.error(msg[:400])
    with c_save:
        if st.button("שמור והרץ", use_container_width=True, key=f"{key_id}_save", type="primary") and pasted.strip():
            try:
                save_polygon_api_key(pasted)
                # New valid key saved -> immediately kick off a fresh scan so
                # the user does not need to find another button.
                try:
                    from src.cloud_scan_job import start_full_scan
                    os.environ["SCAN_ENGINE"] = "apex"
                    start_full_scan("simple")
                except Exception:
                    pass
                st.sidebar.success("נשמר ✓ סריקה חדשה מתחילה…")
                st.rerun()
            except ValueError as exc:
                st.sidebar.error(str(exc))


def _polygon_key_help() -> None:
    with st.sidebar.expander("איזה מפתח לבחור ב-Polygon? (יש לך 6)"):
        st.markdown(
            """
            **השתמש רק ב:**
            - **API Key** / **Default** (מחרוזת ארוכה ~30+ תווים)
            - מנוי **Stocks** פעיל

            **לא להשתמש ב:**
            - Publishable / Client
            - Webhook secret
            - Access Key לקבצי S3

            **לא זוכר איזה?**  
            1. צור **API Key חדש** ב-Polygon  
            2. הדבק כאן → **בדוק** → אם ירוק → **שמור**  
            3. מחק מפתחות ישנים ב-Polygon

            או מהמחשב:
            `python scripts/check_polygon_key.py --file keys.txt`
            (שורה אחת לכל מפתח)
            """
        )


def _last_scan_error_is_polygon_401() -> bool:
    try:
        from src.cloud_scan_job import get_status
    except ImportError:
        return False
    status = get_status()
    if status.get("state") != "error":
        return False
    msg = str(status.get("message") or "")
    return "401" in msg or "Polygon" in msg


def _render_polygon_setup() -> None:
    from src.polygon_key_store import (
        polygon_key_source,
        polygon_key_tail,
        resolve_polygon_api_key,
    )

    st.sidebar.markdown("### 🔑 נתוני שוק (Polygon)")
    key = resolve_polygon_api_key()
    if key:
        # Show connection status. If the last scan failed with a 401-like
        # error, surface a prominent 'replace key' panel because the current
        # key is likely invalid (Render env-set keys cannot be auto-fixed).
        rejected = _last_scan_error_is_polygon_401()
        if rejected:
            st.sidebar.error(
                f"⚠ מפתח Polygon נדחה (401) · מקור: {polygon_key_source()} · …{polygon_key_tail(key)}"
            )
            st.sidebar.caption("הדבק מפתח חדש כאן והוא יחליף את הקודם בכל הסריקות הבאות:")
            _render_polygon_key_form("replace")
            _polygon_key_help()
        else:
            st.sidebar.success(f"מחובר · מקור: {polygon_key_source()} · …{polygon_key_tail(key)}")
            st.sidebar.caption("מחירים אמיתיים מ-Polygon (מותאמים לספליטים)")
            with st.sidebar.expander("🔄 החלף מפתח Polygon"):
                _render_polygon_key_form("replace_optional")
    else:
        st.sidebar.error("אין מפתח Polygon — הסריקה לא תציג מחירי שוק אמיתיים")
        _render_polygon_key_form("init")
        _polygon_key_help()
        st.sidebar.caption(
            "Render: `POLYGON_API_KEY` + `DATA_PROVIDER=polygon` → Deploy"
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
    files = [p for p in REPORTS_DIR.glob("*_report.csv") if is_official_report_csv(p)]
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


def _auto_scan_interval_hours() -> float:
    raw = os.getenv("SCAN_AUTO_INTERVAL_HOURS", "3").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 3.0


def _format_remaining(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}ש׳ {m:02d}ד׳"
    if m:
        return f"{m}ד׳ {s:02d}ש׳"
    return f"{s}ש׳"


def _scan_percent(prog: dict) -> int:
    try:
        return max(0, min(100, int(float(prog.get("percent") or 0))))
    except (TypeError, ValueError):
        return 0


def _compute_scan_rate(status: dict, prog: dict) -> dict:
    import time

    started_at_raw = status.get("started_at")
    try:
        started_at = float(started_at_raw) if started_at_raw else 0.0
    except (TypeError, ValueError):
        started_at = 0.0
    elapsed = max(0.0, time.time() - started_at) if started_at > 0 else 0.0
    try:
        done = int(prog.get("done") or 0)
    except (TypeError, ValueError):
        done = 0
    try:
        total = int(prog.get("total") or 0)
    except (TypeError, ValueError):
        total = 0
    try:
        percent = float(prog.get("percent") or 0)
    except (TypeError, ValueError):
        percent = 0.0
    rate_symbols = (done / elapsed) if elapsed > 0 and done > 0 else 0.0
    rate_percent = (percent / elapsed) if elapsed > 0 and percent > 0 else 0.0
    if rate_symbols > 0 and total > done > 0:
        eta = (total - done) / rate_symbols
    elif rate_percent > 0 and 0 < percent < 100:
        eta = (100.0 - percent) / rate_percent
    else:
        eta = 0.0
    return {
        "elapsed": elapsed, "rate_symbols_per_sec": rate_symbols,
        "rate_percent_per_sec": rate_percent, "eta_seconds": eta,
        "done": done, "total": total, "percent": percent,
    }


def _format_rate(stats: dict) -> str:
    rate = stats["rate_symbols_per_sec"]
    if rate >= 1:
        return f"{rate:.1f}/ש"
    if rate > 0:
        return f"{rate * 60:.0f}/דק"
    rate_pct = stats["rate_percent_per_sec"] * 60.0
    if rate_pct > 0:
        return f"{rate_pct:.1f}%/דק"
    return "—"


def _render_scan_progress_panel() -> None:
    """In-page panel: percent + progress bar while running, error reason if failed.

    Wrapped in a Streamlit fragment so it refreshes every 5 seconds without
    reloading the whole page.
    """

    @_fragment_decorator(5)
    def _panel() -> None:
        try:
            from src.cloud_scan_job import cancel_scan, get_scan_progress, get_status, start_full_scan
        except ImportError:
            return

        status = get_status()
        current_state = status.get("state", "idle")
        last_state = st.session_state.get("apex_last_scan_state")
        st.session_state["apex_last_scan_state"] = current_state

        if current_state == "running":
            prog = get_scan_progress()
            percent = _scan_percent(prog)
            st.markdown(
                f"""
                <div style="
                    background: linear-gradient(90deg, rgba(59,130,246,0.12), rgba(234,179,8,0.10));
                    border: 1px solid rgba(59,130,246,0.45);
                    border-radius: 12px;
                    padding: 0.7rem 1.1rem;
                    margin: 0.5rem 0 0.6rem 0;
                    display:flex;justify-content:space-between;align-items:center;gap:1rem;
                ">
                    <strong style="color:#fbbf24;font-size:1.05rem;">⚡ סריקה רצה</strong>
                    <span style="color:#e2e8f0;font-size:1.8rem;font-weight:700;">{percent}%</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.progress(percent / 100.0)
            cancel_col, _spacer = st.columns([1, 5])
            with cancel_col:
                if st.button("⏹ בטל", key="apex_scan_cancel_main", use_container_width=True):
                    cancel_scan()
                    _safe_rerun_app()
            return

        if current_state in ("error", "cancelled"):
            err = (status.get("message") or "").strip() or "הסריקה נכשלה."
            log_tail = (status.get("log") or "").strip()
            title = "❌ הסריקה נכשלה" if current_state == "error" else "⏹ הסריקה בוטלה"
            color = "#ef4444" if current_state == "error" else "#f59e0b"
            st.markdown(
                f"""
                <div style="
                    background: rgba(239,68,68,0.10);
                    border: 1px solid {color};
                    border-radius: 12px;
                    padding: 0.9rem 1.1rem;
                    margin: 0.5rem 0 0.6rem 0;
                ">
                    <strong style="color:{color};font-size:1.05rem;">{title}</strong>
                    <div style="color:#e2e8f0;margin-top:0.4rem;font-size:0.95rem;white-space:pre-wrap;">{err}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            retry_col, _spacer = st.columns([1, 5])
            with retry_col:
                if st.button("🔁 נסה שוב", key="apex_scan_retry_main", use_container_width=True, type="primary"):
                    os.environ["SCAN_ENGINE"] = "apex"
                    started, _ = start_full_scan("simple")
                    if started:
                        _safe_rerun_app()
            if log_tail:
                with st.expander("פרטים טכניים (לוג)", expanded=False):
                    st.code(log_tail[-3000:])
            return

        # Idle / ok: nothing to render here; if we just transitioned from
        # running -> ok, force a full rerun so the new report loads.
        if last_state == "running":
            _safe_rerun_app()

    _panel()


def _safe_rerun_app() -> None:
    """Trigger a full app rerun even when called from inside a fragment."""
    try:
        st.rerun(scope="app")
    except TypeError:
        st.rerun()


def _fragment_decorator(run_every_seconds: int):
    """Return a Streamlit fragment decorator that re-runs every N seconds.

    Falls back to a no-op (no auto-refresh) on Streamlit versions without
    ``st.fragment`` / ``st.experimental_fragment``. Using a fragment avoids
    reloading the whole page (no flash, scroll preserved, filters preserved).
    """
    spec = f"{max(1, int(run_every_seconds))}s"
    if hasattr(st, "fragment"):
        return st.fragment(run_every=spec)
    if hasattr(st, "experimental_fragment"):
        return st.experimental_fragment(run_every=spec)
    return lambda func: func


def _has_fragment_autorefresh() -> bool:
    return hasattr(st, "fragment") or hasattr(st, "experimental_fragment")


def _inject_auto_refresh(interval_seconds: int) -> None:
    """Fallback page-reload mechanism for Streamlit builds without fragments."""
    if interval_seconds <= 0 or _has_fragment_autorefresh():
        return
    import streamlit.components.v1 as components

    components.html(
        f"""
        <script>
            (function() {{
                if (window.__apexAutoReload) return;
                window.__apexAutoReload = true;
                setTimeout(function() {{
                    try {{ window.parent.location.reload(); }}
                    catch (e) {{ window.location.reload(); }}
                }}, {int(interval_seconds * 1000)});
            }})();
        </script>
        """,
        height=0,
    )


def _has_existing_scan_report() -> bool:
    """True when a prior scan report is on disk (or persisted metadata)."""
    if _discover_reports():
        return True
    saved = load_last_report()
    name = str(saved.get("report_file") or "").strip()
    if not name:
        return False
    path = REPORTS_DIR / name
    return path.is_file() and path.stat().st_size > 0


def _start_apex_scan() -> None:
    os.environ["SCAN_ENGINE"] = "apex"
    from src.cloud_scan_job import start_full_scan

    return start_full_scan("simple")


def _cloud_scan_ui() -> None:
    try:
        from src.cloud_scan_job import (
            cancel_scan,
            get_scan_progress,
            get_status,
            maybe_auto_run_scan,
            seconds_until_next_auto_scan,
            start_full_scan,
        )
    except ImportError:
        return

    st.sidebar.markdown("### ▶ סריקה")

    default_interval = _auto_scan_interval_hours()
    options = [0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0]
    if default_interval not in options:
        options.append(default_interval)
        options.sort()
    default_idx = options.index(default_interval) if default_interval in options else options.index(3.0)
    interval_choice = st.sidebar.selectbox(
        "סריקה אוטומטית כל…",
        options,
        index=default_idx,
        format_func=lambda v: "כבוי (ידני בלבד)" if v == 0 else f"{int(v) if v.is_integer() else v} שעות",
        key="apex_auto_interval_hours",
        help="סורק מחדש אוטומטית כל X שעות כל עוד הדפדפן פתוח.",
    )
    interval_hours = float(interval_choice)

    status = get_status()
    state = status.get("state", "idle")

    if state != "running" and interval_hours > 0:
        triggered, _msg = maybe_auto_run_scan("simple", interval_hours=interval_hours)
        if triggered:
            status = get_status()
            state = status.get("state", "idle")

    if state == "running":
        prog = get_scan_progress()
        stats = _compute_scan_rate(status, prog)
        percent = _scan_percent(prog)
        st.sidebar.progress(percent / 100.0)
        st.sidebar.caption(prog.get("message", "רץ…"))

        done, total = stats["done"], stats["total"]
        counter = f"{done:,}/{total:,}" if total else (f"{done:,}" if done else "—")
        elapsed_str = _format_remaining(stats["elapsed"]) if stats["elapsed"] else "—"
        eta_str = _format_remaining(stats["eta_seconds"]) if stats["eta_seconds"] > 0 else "—"

        sm1, sm2 = st.sidebar.columns(2)
        sm1.metric("התקדמות", counter)
        sm2.metric("מהירות", _format_rate(stats))
        sm3, sm4 = st.sidebar.columns(2)
        sm3.metric("עבר", elapsed_str)
        sm4.metric("נותר", eta_str)

        c_cancel, c_refresh = st.sidebar.columns(2)
        with c_cancel:
            if st.button("⏹ בטל", use_container_width=True, key="apex_scan_cancel"):
                cancel_scan()
                st.rerun()
        with c_refresh:
            if st.button("🔄 רענן", use_container_width=True, key="apex_scan_refresh"):
                st.rerun()
        # Fragment-based refresh handles live updates of the in-page panel.
        _inject_auto_refresh(30)
    else:
        has_report = _has_existing_scan_report()
        run_label = "🔄 עדכון סריקה" if has_report else "▶ הרץ Apex Scan עכשיו"
        run_help = (
            "מריץ סריקה מחדש ומעדכן את הדוח (אותה רמת simple)."
            if has_report
            else "סריקה ראשונה — דוח Apex חדש."
        )
        if st.sidebar.button(
            run_label,
            type="primary",
            use_container_width=True,
            key="apex_scan_manual",
            help=run_help,
        ):
            started, msg = _start_apex_scan()
            if started:
                st.sidebar.success(msg)
            else:
                st.sidebar.warning(msg)
            st.rerun()

        if interval_hours > 0:
            remaining = seconds_until_next_auto_scan(interval_hours)
            if remaining == float("inf"):
                st.sidebar.caption("סריקה אוטומטית כבויה")
            elif remaining <= 0:
                st.sidebar.caption("סריקה אוטומטית: מתחילה כעת…")
            else:
                st.sidebar.caption(f"⏱ סריקה אוטומטית הבאה בעוד {_format_remaining(remaining)}")
            poll = max(60, min(300, int(remaining))) if remaining > 0 else 10
            _inject_auto_refresh(poll)
        else:
            st.sidebar.caption("סריקה אוטומטית כבויה — לחץ על הכפתור להרצה ידנית")


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
    _render_scan_progress_panel()

    reports = _discover_reports()
    if not reports:
        st.info(
            "אין דוח. לחץ **▶ הרץ Apex Scan עכשיו** בסרגל (סעיף סריקה) "
            "או הרץ: `python scripts/run_apex_scanner.py`"
        )
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
