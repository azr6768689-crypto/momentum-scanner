"""Normalize secrets pasted into cloud env vars (quotes, whitespace)."""

from __future__ import annotations


def clean_env_secret(value: str) -> str:
    v = (value or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1].strip()
    return v
