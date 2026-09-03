#!/bin/bash
# Re-creates everything OptCD needs beyond this repo itself: a local clone of
# the fork you're optimizing, and a sanity check on credentials/tools. Safe
# to re-run any time (e.g. after deleting your workdir) -- it only clones
# what's missing and never touches anything that already exists.
#
# Usage: ./bootstrap.sh <github-owner>/<repo> [path-to-clone-into]
#   e.g. ./bootstrap.sh atanuroy911/jsoup ../jsoup

set -e

owner_repo="$1"
dest="${2:-../$(basename "$owner_repo")}"

if [ -z "$owner_repo" ]; then
  echo "Usage: ./bootstrap.sh <github-owner>/<repo> [path-to-clone-into]"
  exit 1
fi

fail=0

echo "== Checking tools =="

if ! command -v git >/dev/null 2>&1; then
  echo "[MISSING] git is not on PATH."
  fail=1
else
  echo "[OK] git"
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "[MISSING] GitHub CLI (gh) is not on PATH."
  echo "          Install: https://cli.github.com  (Windows: winget install --id GitHub.cli)"
  fail=1
else
  echo "[OK] gh ($(gh --version | head -n1))"
  if gh auth status >/dev/null 2>&1; then
    echo "[OK] gh is authenticated"
  else
    echo "[MISSING] gh is not authenticated. Run: gh auth login && gh auth setup-git"
    fail=1
  fi
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "[MISSING] python3 is not on PATH."
  echo "          On Windows, the Microsoft Store 'python3' alias is often a"
  echo "          non-functional stub -- point it at your real Python instead,"
  echo "          e.g. a one-line shim script on PATH: exec python \"\$@\""
  fail=1
else
  echo "[OK] python3 ($(python3 --version 2>&1))"
fi

echo ""
echo "== Checking credentials =="

if [ -f ".env" ]; then
  echo "[OK] .env exists"
  if ! grep -q "^GITHUB_API_TOKEN=" .env || ! grep -q "^GEMINI_API_KEY=" .env; then
    echo "[MISSING] .env exists but is missing GITHUB_API_TOKEN and/or GEMINI_API_KEY"
    fail=1
  fi
else
  echo "[MISSING] .env not found. Create one with:"
  echo "            GITHUB_API_TOKEN=<your-github-token>"
  echo "            GEMINI_API_KEY=<your-gemini-key>"
  fail=1
fi

echo ""
echo "== Checking Python dependencies =="
pip install -r requirements.txt >/dev/null 2>&1 && echo "[OK] requirements installed" || echo "[WARN] pip install had issues -- check manually"

echo ""
echo "== Checking target repo clone =="

if [ -d "$dest/.git" ]; then
  echo "[OK] $dest already exists, leaving it as-is"
else
  echo "Cloning https://github.com/$owner_repo.git into $dest ..."
  git clone "https://github.com/$owner_repo.git" "$dest"
  echo "[OK] cloned"
fi

echo ""
if [ "$fail" -ne 0 ]; then
  echo "One or more checks failed above -- fix those before running optcd.sh."
  exit 1
fi

echo "Everything looks ready. Example run:"
echo "  set -a; source .env; set +a"
echo "  ./optcd.sh \"$dest/.github/workflows/<workflow>.yml\" \"$dest/.github/workflows/opt-<workflow>.yml\""
