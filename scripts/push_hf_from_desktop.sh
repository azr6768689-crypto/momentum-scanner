#!/usr/bin/env bash
# מעלה את הסורק ל-Hugging Face Space (אסימון משולחן העבודה)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TOKEN_FILE="$HOME/Desktop/hf_token.txt"
USER_FILE="$HOME/Desktop/hf_username.txt"

if [[ ! -f "$TOKEN_FILE" ]]; then
  echo "צור קובץ: $TOKEN_FILE"
  echo "הדבק אסימון Write מ: https://huggingface.co/settings/tokens"
  exit 1
fi

export HF_TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"
if [[ ${#HF_TOKEN} -lt 20 ]]; then
  echo "אסימון HF קצר מדי או ריק."
  exit 1
fi

if [[ -f "$USER_FILE" ]]; then
  export HF_USERNAME="$(tr -d '[:space:]' < "$USER_FILE")"
fi
if [[ -z "${HF_USERNAME:-}" ]]; then
  echo "צור קובץ: $USER_FILE"
  echo "שורה אחת — שם המשתמש שלך ב-Hugging Face (למעלה בפרופיל)"
  exit 1
fi

export HF_SPACE_NAME="${HF_SPACE_NAME:-momentum-scanner}"

bash scripts/prepare_hf_upload.sh
python3 scripts/upload_to_huggingface.py

# סודות מ-.env אם קיים
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [[ -n "${POLYGON_API_KEY:-}" && -n "${DASHBOARD_PASSWORD:-}" ]]; then
  python3 <<'PY'
import os
from huggingface_hub import HfApi

api = HfApi(token=os.environ["HF_TOKEN"])
repo = f"{os.environ['HF_USERNAME']}/{os.environ.get('HF_SPACE_NAME', 'momentum-scanner')}"
for key, val in [
    ("POLYGON_API_KEY", os.environ["POLYGON_API_KEY"]),
    ("DASHBOARD_PASSWORD", os.environ["DASHBOARD_PASSWORD"]),
    ("DATA_PROVIDER", "polygon"),
    ("RUN_SCAN_ON_STARTUP", "false"),
]:
    api.add_space_secret(repo_id=repo, key=key, value=val)
    print(f"Secret הוגדר: {key}")
print(f"Space: https://huggingface.co/spaces/{repo}")
PY
else
  echo ""
  echo "הוסף ידנית ב-Space → Settings → Secrets:"
  echo "  POLYGON_API_KEY, DASHBOARD_PASSWORD, DATA_PROVIDER=polygon"
fi

rm -f "$TOKEN_FILE"
echo "אסימון HF נמחק מ-Desktop (hf_token.txt)."
