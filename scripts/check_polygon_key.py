#!/usr/bin/env python3
"""בדוק מפתח Polygon בלי להדפיס אותו במלואו."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _check_one(raw: str, label: str) -> bool:
    from src.polygon_key_store import normalize_polygon_key, polygon_key_tail
    from src.polygon_preflight import validate_key_format, validate_polygon_api_key

    key = normalize_polygon_key(raw)
    if not key:
        print(f"[{label}] ריק — דילוג")
        return False
    tail = polygon_key_tail(key)
    ok_fmt, fmt = validate_key_format(key)
    if not ok_fmt:
        print(f"[{label}] …{tail} — פורמט: {fmt}")
        return False
    ok, msg = validate_polygon_api_key(key)
    if ok:
        print(f"[{label}] …{tail} — ✅ תקין · מתאים לסורק")
        return True
    print(f"[{label}] …{tail} — ❌ {msg}")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="בדיקת מפתח/ות Polygon")
    parser.add_argument(
        "--file",
        type=Path,
        help="קובץ עם מפתח אחד בכל שורה (לא יוצג במלואו)",
    )
    parser.add_argument("keys", nargs="*", help="מפתחות להדבקה (אופציונלי)")
    args = parser.parse_args()

    keys_to_test: list[tuple[str, str]] = []

    if args.file and args.file.is_file():
        for i, line in enumerate(args.file.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip() and not line.strip().startswith("#"):
                keys_to_test.append((f"שורה {i}", line.strip()))
    elif args.keys:
        for i, k in enumerate(args.keys, 1):
            keys_to_test.append((f"מפתח {i}", k))
    else:
        from src.polygon_key_store import resolve_polygon_api_key

        stored = resolve_polygon_api_key()
        if stored:
            keys_to_test.append(("שמור במערכת", stored))
        else:
            print("אין מפתח שמור. הדבק מפתחים:")
            print("  python scripts/check_polygon_key.py 'מפתח1' 'מפתח2'")
            print("  או: מפתחות.txt (שורה לכל מפתח) → --file מפתחות.txt")
            return 1

    print("בודק מפתחות מול Polygon (AAPL)…\n")
    winners = 0
    for label, raw in keys_to_test:
        if _check_one(raw, label):
            winners += 1
        print()

    print("—" * 50)
    if winners == 0:
        print("אף מפתח לא עבר. ב-Polygon צור **API Key חדש** (Default) עם מנוי Stocks.")
        return 1
    if winners == 1:
        print("יש מפתח אחד תקין — השתמש בו ב-Render ובדשבורד (שמור מפתח).")
        return 0
    print(f"{winners} מפתחות תקינים — בחר אחד, מחק את הישנים ב-Polygon לבלבול.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
