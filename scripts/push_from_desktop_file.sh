#!/usr/bin/env bash
# קורא אסימון מקובץ על שולחן העבודה ודוחף ל-GitHub.
set -euo pipefail
TOKEN_FILE="$HOME/Desktop/github_token.txt"
cd "$(dirname "$0")/.."

if [[ ! -f "$TOKEN_FILE" ]]; then
  echo "צור קובץ: $TOKEN_FILE"
  echo "הדבק בו רק את האסימון (שורה אחת, מתחיל ב-ghp_)"
  exit 1
fi

export GITHUB_TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"
export GITHUB_USER="${GITHUB_USER:-azr6768689-crypto}"

if [[ ${#GITHUB_TOKEN} -lt 20 ]]; then
  echo "הקובץ ריק או האסימון קצר מדי."
  exit 1
fi

bash "$(dirname "$0")/push_to_github.sh"
rm -f "$TOKEN_FILE"
echo "אסימון נמחק מהמחשב (הקובץ הוסר)."
