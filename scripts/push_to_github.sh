#!/usr/bin/env bash
# יוצר ריפו ב-GitHub (אם חסר) ודוחף את הקוד. דורש Personal Access Token.
set -euo pipefail
cd "$(dirname "$0")/.."

USER="${GITHUB_USER:-}"
REPO="${GITHUB_REPO:-momentum-scanner}"
TOKEN="${GITHUB_TOKEN:-}"

if [[ -z "$USER" || -z "$TOKEN" ]]; then
  echo ""
  echo "חסר GITHUB_USER או GITHUB_TOKEN."
  echo "צור Token: https://github.com/settings/tokens → Generate (classic) → repo"
  echo ""
  echo "  export GITHUB_USER='שם_המשתמש'"
  echo "  export GITHUB_TOKEN='ghp_...'"
  echo "  bash scripts/push_to_github.sh"
  echo ""
  exit 1
fi

if ! git remote get-url github &>/dev/null; then
  git remote add github "https://${USER}@github.com/${USER}/${REPO}.git"
else
  git remote set-url github "https://${USER}@github.com/${USER}/${REPO}.git"
fi

code=$(curl -s -o /tmp/gh_create.json -w "%{http_code}" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  -d "{\"name\":\"${REPO}\",\"private\":true}" \
  "https://api.github.com/user/repos")

if [[ "$code" == "201" ]]; then
  echo "ריפו נוצר ב-GitHub: ${USER}/${REPO}"
elif [[ "$code" == "422" ]]; then
  echo "ריפו כבר קיים — ממשיך לדחיפה."
else
  echo "יצירת ריפו החזירה ${code}:"
  cat /tmp/gh_create.json
  echo ""
fi

git push "https://${USER}:${TOKEN}@github.com/${USER}/${REPO}.git" main
git branch --set-upstream-to=github/main main 2>/dev/null || true

echo ""
echo "הועלה: https://github.com/${USER}/${REPO}"
echo "המשך: Render.com → New Web Service → חבר GitHub → בחר ${REPO}"
