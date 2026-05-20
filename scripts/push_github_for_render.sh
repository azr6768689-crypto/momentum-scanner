#!/usr/bin/env bash
# Push current branch to the 'github' remote so Render Blueprint can pull latest code.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if ! git remote get-url github >/dev/null 2>&1; then
  echo "No git remote named 'github'. Add it, e.g.:"
  echo "  git remote add github https://github.com/YOUR_USER/momentum-scanner.git"
  exit 1
fi
echo "Pushing ${BRANCH} → github/${BRANCH} ..."
git push github "${BRANCH}"
