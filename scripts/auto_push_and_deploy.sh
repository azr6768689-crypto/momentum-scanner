#!/usr/bin/env bash
# Push main to GitHub and note Render auto-deploy. Uses gh CLI or GITHUB_TOKEN.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
GH="${GH_BIN:-/tmp/ghcli/gh_2.92.0_macOS_arm64/bin/gh}"

push_git() {
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    git push "https://${GITHUB_TOKEN}@github.com/azr6768689-crypto/momentum-scanner.git" main
    return
  fi
  if "$GH" auth status >/dev/null 2>&1; then
    "$GH" auth setup-git
    git push github main
    return
  fi
  echo "No GitHub auth. Set GITHUB_TOKEN or run: gh auth login --web"
  exit 1
}

echo "Pushing to GitHub..."
push_git
echo "Done: https://github.com/azr6768689-crypto/momentum-scanner"
echo "Render should auto-deploy in ~3 min: https://momentum-scanner-bbhl.onrender.com"
