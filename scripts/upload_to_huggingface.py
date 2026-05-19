#!/usr/bin/env python3
"""Upload prepared hf_space_upload/ to a Hugging Face Space (Streamlit)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR = ROOT / "hf_space_upload"


def main() -> int:
    token = os.getenv("HF_TOKEN", "").strip()
    username = os.getenv("HF_USERNAME", "").strip()
    space_name = os.getenv("HF_SPACE_NAME", "momentum-scanner").strip()

    if not token:
        print("חסר HF_TOKEN — צור אסימון ב: https://huggingface.co/settings/tokens (Write)")
        print("ואז במסוף:")
        print("  export HF_TOKEN='האסימון'")
        print("  export HF_USERNAME='שם_המשתמש_שלך'")
        print("  python3 scripts/upload_to_huggingface.py")
        return 1

    if not username:
        print("חסר HF_USERNAME — שם המשתמש שלך ב-Hugging Face (למעלה בפרופיל)")
        return 1

    if not UPLOAD_DIR.is_dir():
        print("חסרה תיקיית hf_space_upload — הרץ קודם: bash scripts/prepare_hf_upload.sh")
        return 1

    try:
        from huggingface_hub import HfApi
    except ImportError:
        print("מתקין huggingface_hub...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "huggingface_hub", "-q"])
        from huggingface_hub import HfApi

    repo_id = f"{username}/{space_name}"
    api = HfApi(token=token)

    print(f"יוצר Space (אם חסר): {repo_id}")
    api.create_repo(
        repo_id=repo_id,
        repo_type="space",
        space_sdk="streamlit",
        private=True,
        exist_ok=True,
    )

    print("מעלה קבצים... (יכול לקחת כמה דקות)")
    api.upload_folder(
        folder_path=str(UPLOAD_DIR),
        repo_id=repo_id,
        repo_type="space",
        commit_message="Upload momentum scanner",
    )

    url = f"https://huggingface.co/spaces/{repo_id}"
    print("")
    print("הועלה בהצלחה.")
    print(f"פתח: {url}")
    print("")
    print("עכשיו ב-Settings → Secrets הוסף:")
    print("  POLYGON_API_KEY, DASHBOARD_PASSWORD, DATA_PROVIDER=polygon")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
