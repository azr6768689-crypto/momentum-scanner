#!/usr/bin/env bash
# Push local main to GitHub using a Personal Access Token (no interactive password).
# 1) Create token: https://github.com/settings/tokens  → scope: repo (full control of private repositories)
# 2) Run:  export GITHUB_TOKEN=ghp_xxxxxxxx
#          bash scripts/push_github_pat.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

REPO_SLUG="azr6768689-crypto/momentum-scanner"
TOKEN="${GITHUB_TOKEN:-}"

if [[ -z "$TOKEN" ]]; then
  echo "חסר GITHUB_TOKEN."
  echo "צור אסימון: https://github.com/settings/tokens (סימון: repo)"
  echo "ואז: export GITHUB_TOKEN=ghp_......"
  echo "     bash scripts/push_github_pat.sh"
  exit 1
fi

echo "דוחף ל־github.com/${REPO_SLUG} (ענף main)..."
# Token in URL: fine for one-off local run; avoid sharing screen recordings.
git push "https://${TOKEN}@github.com/${REPO_SLUG}.git" main

echo "בוצע. בדוק: https://github.com/${REPO_SLUG}/tree/main"
echo "אם Render היה תקוע — לחץ Retry אחרי ש־render.yaml מופיע בגיטהאב."
