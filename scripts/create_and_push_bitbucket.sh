#!/usr/bin/env bash
# יוצר ריפו ב-Bitbucket (אם חסר) ודוחף את הקוד. דורש API token עם הרשאות Bitbucket.
set -euo pipefail
cd "$(dirname "$0")/.."

WORKSPACE="${BITBUCKET_WORKSPACE:-sorek}"
REPO="${BITBUCKET_REPO:-hdsh}"
USER="${BITBUCKET_USER:-AZR72161}"

# אפשר להעביר אסימון כפרמטר: bash scripts/create_and_push_bitbucket.sh 'האסימון'
if [[ $# -ge 1 ]]; then
  BITBUCKET_TOKEN="$1"
fi

if [[ -z "${BITBUCKET_TOKEN:-}" ]]; then
  echo ""
  echo "חסר אסימון. אחת מהאפשרויות:"
  echo "  export BITBUCKET_TOKEN='האסימון'   ← חובה המילה export"
  echo "  bash scripts/create_and_push_bitbucket.sh 'האסימון'"
  echo ""
  exit 1
fi

auth() { echo -n "${USER}:${BITBUCKET_TOKEN}" | base64 | tr -d '\n'; }

echo "בודק workspace..."
ws_code=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Basic $(auth)" \
  "https://api.bitbucket.org/2.0/repositories/${WORKSPACE}/${REPO}")

if [[ "$ws_code" == "404" ]]; then
  echo "יוצר ריפו ${WORKSPACE}/${REPO} ..."
  create_code=$(curl -s -o /tmp/bb_create.json -w "%{http_code}" \
    -X POST \
    -H "Authorization: Basic $(auth)" \
    -H "Content-Type: application/json" \
    -d '{"scm":"git","is_private":true}' \
    "https://api.bitbucket.org/2.0/repositories/${WORKSPACE}/${REPO}")
  if [[ "$create_code" != "200" && "$create_code" != "201" ]]; then
    echo "לא הצלחתי ליצור ריפו (קוד ${create_code}). תשובת השרת:"
    cat /tmp/bb_create.json
    echo ""
    echo "נסה בדפדפן: https://bitbucket.org/repo/create — שם: ${REPO}"
    exit 1
  fi
  echo "ריפו נוצר."
elif [[ "$ws_code" == "200" ]]; then
  echo "ריפו כבר קיים."
else
  echo "בדיקת ריפו החזירה קוד ${ws_code}"
fi

export BITBUCKET_USER="${BITBUCKET_USER}"
export BITBUCKET_TOKEN="${BITBUCKET_TOKEN}"
export BITBUCKET_WORKSPACE="${WORKSPACE}"
export BITBUCKET_REPO="${REPO}"
exec ./scripts/push_to_bitbucket.sh
