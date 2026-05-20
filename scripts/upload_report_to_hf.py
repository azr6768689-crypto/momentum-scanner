#!/usr/bin/env python3
"""Upload one report CSV to Hugging Face Space (data/reports/)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "data" / "reports"


def _latest_report() -> Path | None:
    candidates = sorted(
        REPORTS.glob("*_report.csv"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def main() -> int:
    token = os.getenv("HF_TOKEN", "").strip()
    username = os.getenv("HF_USERNAME", "azr6768689").strip()
    space = os.getenv("HF_SPACE_NAME", "momentum-scanner").strip()

    if len(sys.argv) > 1:
        report = Path(sys.argv[1]).expanduser()
        if not report.is_absolute():
            report = ROOT / report
    else:
        report = _latest_report()

    if not token:
        print("חסר HF_TOKEN — שים hf_token.txt על שולחן העבודה והרץ:")
        print("  bash scripts/full_scan_and_publish.sh")
        return 1

    if not report or not report.is_file():
        print(f"לא נמצא דוח ב-{REPORTS}")
        return 1

    try:
        from huggingface_hub import HfApi
    except ImportError:
        import subprocess

        subprocess.check_call([sys.executable, "-m", "pip", "install", "huggingface_hub", "-q"])
        from huggingface_hub import HfApi

    repo_id = f"{username}/{space}"
    path_in_repo = f"data/reports/{report.name}"
    api = HfApi(token=token)

    print(f"מעלה: {report.name} ({report.stat().st_size / 1_000_000:.1f} MB)")
    api.upload_file(
        path_or_fileobj=str(report),
        path_in_repo=path_in_repo,
        repo_id=repo_id,
        repo_type="space",
        commit_message=f"Update report {report.name}",
    )
    print("")
    print("הועלה.")
    print(f"פתח: https://huggingface.co/spaces/{repo_id}")
    print(f"בחר בדוח: {report.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
