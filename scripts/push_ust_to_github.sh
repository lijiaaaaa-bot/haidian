#!/usr/bin/env bash
# Run on your Mac where urban-spatial-tooling lives.
# Creates lijiaaaaa-bot/urban-spatial-tooling (private) and pushes.
#
#   chmod +x scripts/push_ust_to_github.sh
#   ./scripts/push_ust_to_github.sh
#   # or: UST_DIR=/path/to/urban-spatial-tooling ./scripts/push_ust_to_github.sh

set -euo pipefail

UST_DIR="${UST_DIR:-$HOME/Projects/urban-spatial-tooling}"
GITHUB_OWNER="${GITHUB_OWNER:-lijiaaaaa-bot}"
REPO_NAME="${REPO_NAME:-urban-spatial-tooling}"
VISIBILITY="${VISIBILITY:-private}"

if [[ ! -d "$UST_DIR" ]]; then
  echo "ERROR: UST project not found: $UST_DIR"
  echo "Set UST_DIR=/Users/lijia/Projects/urban-spatial-tooling if path differs."
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR: GitHub CLI (gh) required. Install: brew install gh && gh auth login"
  exit 1
fi

echo "==> GitHub account:"
gh auth status

cd "$UST_DIR"

if [[ ! -d .git ]]; then
  echo "==> git init"
  git init -b main
fi

# Ensure .gitignore exists
if [[ ! -f .gitignore ]]; then
  cat > .gitignore <<'EOF'
__pycache__/
*.py[cod]
.venv/
venv/
.env
.DS_Store
*.egg-info/
dist/
build/
.pytest_cache/
.mypy_cache/
.ipynb_checkpoints/
EOF
fi

git add -A
if git diff --cached --quiet; then
  echo "==> No changes to commit (already clean)"
else
  git commit -m "Initial commit: urban-spatial-tooling for haidian UST figures"
fi

REMOTE="git@github.com:${GITHUB_OWNER}/${REPO_NAME}.git"

if ! gh repo view "${GITHUB_OWNER}/${REPO_NAME}" >/dev/null 2>&1; then
  echo "==> Creating ${VISIBILITY} repo ${GITHUB_OWNER}/${REPO_NAME}"
  gh repo create "${GITHUB_OWNER}/${REPO_NAME}" \
    --"${VISIBILITY}" \
    --description "Urban spatial tooling — EPSG:4548 figure generation for haidian submissions" \
    --source=. \
    --remote=origin \
    --push
else
  echo "==> Repo exists, pushing to origin"
  if git remote | grep -q '^origin$'; then
    git remote set-url origin "$REMOTE"
  else
    git remote add origin "$REMOTE"
  fi
  git push -u origin main
fi

echo ""
echo "OK: https://github.com/${GITHUB_OWNER}/${REPO_NAME}"
echo "Cloud Agent can then:"
echo "  git clone https://github.com/${GITHUB_OWNER}/${REPO_NAME}.git /workspace/urban-spatial-tooling"
echo "  UST_ROOT=/workspace/urban-spatial-tooling python3 scripts/generate_submission_figures.py submissions/lijiaaaaa-bot/jingzhang-zhimai-belt"
