#!/usr/bin/env bash
# העלאה חד-פעמית ל-Bitbucket עם API token או Repository access token.
set -euo pipefail
cd "$(dirname "$0")/.."

WORKSPACE="${BITBUCKET_WORKSPACE:-sorek}"
REPO="${BITBUCKET_REPO:-hdsh}"
# API token מ-Atlassian: שם משתמש Bitbucket (למשל AZR72161)
# Repository access token מהריפו: BITBUCKET_USER=x-token-auth
USER="${BITBUCKET_USER:-AZR72161}"
REMOTE="https://${USER}@bitbucket.org/${WORKSPACE}/${REPO}.git"
git remote set-url origin "$REMOTE"

if [[ $# -ge 1 ]]; then
  BITBUCKET_TOKEN="$1"
fi

if [[ -z "${BITBUCKET_TOKEN:-}" ]]; then
  echo ""
  echo "חסר אסימון. לדוגמה:"
  echo "  export BITBUCKET_TOKEN='האסימון'"
  echo "  bash scripts/push_to_bitbucket.sh 'האסימון'"
  echo ""
  exit 1
fi

if [[ ${#BITBUCKET_TOKEN} -lt 20 ]]; then
  echo "האסימון קצר מדי — כנראה נחתך. השתמש בגרשיים: export BITBUCKET_TOKEN='...'" >&2
  exit 1
fi

if ! git push "https://${USER}:${BITBUCKET_TOKEN}@bitbucket.org/${WORKSPACE}/${REPO}.git" main; then
  echo "" >&2
  echo "נכשל. בדוק:" >&2
  echo "  1) בדפדפן: https://bitbucket.org/${WORKSPACE}/${REPO} — האם הריפו קיים?" >&2
  echo "  2) האסימון עם גרשיים: export BITBUCKET_TOKEN='...'" >&2
  echo "  3) או צור Repository access token בריפו → BITBUCKET_USER=x-token-auth" >&2
  exit 1
fi

git branch --set-upstream-to=origin/main main 2>/dev/null || true
echo ""
echo "הועלה בהצלחה ל-Bitbucket: ${WORKSPACE}/${REPO}"
