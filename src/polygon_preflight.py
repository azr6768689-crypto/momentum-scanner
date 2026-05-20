"""Shared Polygon API key validation."""

from __future__ import annotations

import requests

from src.polygon_key_store import polygon_key_tail, resolve_polygon_api_key

_API_URLS = (
    "https://api.polygon.io/v3/reference/tickers/AAPL",
    "https://api.massive.com/v3/reference/tickers/AAPL",
)


def validate_polygon_api_key(key: str | None = None) -> tuple[bool, str]:
    key = (key or resolve_polygon_api_key()).strip()
    if not key:
        return (
            False,
            "חסר מפתח Polygon. הדבק מפתח חדש למטה או ב-Render → POLYGON_API_KEY.",
        )
    try:
        for url in _API_URLS:
            for auth_mode in ("query", "bearer"):
                if auth_mode == "query":
                    resp = requests.get(url, params={"apiKey": key}, timeout=20)
                else:
                    resp = requests.get(
                        url,
                        headers={"Authorization": f"Bearer {key}"},
                        timeout=20,
                    )
                if resp.status_code == 401:
                    continue
                if resp.status_code == 403:
                    return (
                        False,
                        f"מפתח ללא הרשאה (403) · מסתיים ב-{polygon_key_tail(key)}",
                    )
                if resp.status_code >= 400:
                    return False, f"Polygon שגיאה {resp.status_code}: {resp.text[:160]}"
                return True, "ok"
        return (
            False,
            f"מפתח נדחה (401) · מסתיים ב-{polygon_key_tail(key)}. "
            "צור מפתח חדש ב-polygon.io/dashboard/api-keys והדבק למטה.",
        )
    except Exception as exc:
        return False, f"לא הצלחתי לבדוק את Polygon: {exc}"
