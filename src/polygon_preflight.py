"""Shared Polygon API key validation."""

from __future__ import annotations

import re

import requests

from src.polygon_key_store import normalize_polygon_key, polygon_key_tail

# Same endpoints the scanner uses (v2 aggregates), not only v3 reference.
_CHECK_URLS = (
    (
        "https://api.polygon.io/v2/aggs/ticker/AAPL/prev",
        "query",
    ),
    (
        "https://api.polygon.io/v3/reference/tickers/AAPL",
        "query",
    ),
    (
        "https://api.massive.com/v2/aggs/ticker/AAPL/prev",
        "query",
    ),
)


def validate_key_format(key: str) -> tuple[bool, str]:
    if len(key) < 20:
        return (
            False,
            f"המפתח קצר מדי ({len(key)} תווים). העתק את **כל** המפתח מ-API Keys (בדרך כלל 30+ תווים).",
        )
    if key.startswith("ghp_") or key.startswith("github_"):
        return False, "זה נראה כמו GitHub token — לא מפתח Polygon."
    if key.startswith("hf_"):
        return False, "זה נראה כמו Hugging Face token — לא מפתח Polygon."
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", key):
        return False, "המפתח מכיל תווים לא חוקיים (רווח, גרשיים, עברית?). הדבק שוב בלי רווחים."
    return True, "ok"


def validate_polygon_api_key(key: str | None = None) -> tuple[bool, str]:
    from src.polygon_key_store import resolve_polygon_api_key

    key = normalize_polygon_key(key or "")
    if not key:
        key = resolve_polygon_api_key()
    if not key:
        return (
            False,
            "חסר מפתח Polygon. הדבק מפתח חדש למטה.",
        )
    ok_fmt, fmt_msg = validate_key_format(key)
    if not ok_fmt:
        return False, fmt_msg

    last_error = ""
    try:
        for url, auth_mode in _CHECK_URLS:
            if auth_mode == "query":
                resp = requests.get(url, params={"apiKey": key}, timeout=10)
            else:
                resp = requests.get(
                    url,
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=10,
                )
            if resp.status_code == 200:
                return True, "ok"
            if resp.status_code == 401:
                try:
                    last_error = resp.json().get("error", "Unauthorized")
                except Exception:
                    last_error = "Unauthorized"
                continue
            if resp.status_code == 403:
                return (
                    False,
                    f"המפתח התקבל אבל אין מנוי לנתוני מניות (403). "
                    f"נדרש מנוי Stocks ב-polygon.io · …{polygon_key_tail(key)}",
                )
            last_error = f"HTTP {resp.status_code}: {resp.text[:120]}"
        return (
            False,
            f"Polygon דוחה את המפתח (401: {last_error}) · …{polygon_key_tail(key)}. "
            "ודא: Dashboard → API Keys → **Default** key (לא Publishable). "
            "אם אין מנוי פעיל — הפעל/חדש מנוי Stocks.",
        )
    except Exception as exc:
        return False, f"לא הצלחתי לבדוק את Polygon (רשת): {exc}"
