#!/usr/bin/env bash
# Builds a folder ready to push to a Hugging Face Space.
#
# A Space reads its settings from the YAML at the top of README.md, so the Space copy
# uses deploy/huggingface/README.md as its README. Everything else is the same code.
# This script only copies files; it does not run git or upload anything.
#
# Usage:
#   deploy/huggingface/prepare_space.sh <empty-folder>                 # model downloads at build time
#   deploy/huggingface/prepare_space.sh <empty-folder> --with-models   # ship the model files in the Space repo
#
# --with-models copies backend/models (about 250 MB) and checks every file first. Pushing
# files that large to a Space needs git-xet or git-lfs installed (see deploy/DEPLOY.md).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${1:-}"
WITH_MODELS=0
[ "${2:-}" = "--with-models" ] && WITH_MODELS=1

if [ -z "$OUT" ]; then
  echo "usage: deploy/huggingface/prepare_space.sh <empty-folder> [--with-models]" >&2
  exit 64
fi
parent="$(cd "$(dirname "$OUT")" 2>/dev/null && pwd)" \
  || { echo "prepare_space: the folder above $OUT does not exist" >&2; exit 1; }
OUT="$parent/$(basename "$OUT")"
case "$OUT" in
  "$ROOT"|"$ROOT"/*) echo "prepare_space: pick a folder outside the repo" >&2; exit 1 ;;
esac
mkdir -p "$OUT"
if [ -n "$(ls -A "$OUT" | grep -v '^\.git$' || true)" ]; then
  echo "prepare_space: $OUT is not empty (only a .git folder is allowed)" >&2
  exit 1
fi

excludes=(
  --exclude '.git/' --exclude '.env' --exclude '.env.*'
  --exclude '.secrets/' --exclude '*.pem' --exclude '*.key'
  --exclude '.claude/' --exclude '.claude-flow/' --exclude '.swarm/' --exclude '.hive-mind/'
  --exclude '__pycache__/' --exclude '*.pyc' --exclude '.pytest_cache/' --exclude '.venv/'
  --exclude 'node_modules/' --exclude 'frontend/dist/' --exclude '*.tsbuildinfo'
  --exclude '.vercel/' --exclude 'backend/tmp/' --exclude '/tmp/' --exclude '/data/'
  --exclude '.DS_Store' --exclude '*.log' --exclude 'solace-models-*.tar.gz'
  --exclude 'docs/submission/'
)
if [ "$WITH_MODELS" -eq 1 ]; then
  "$ROOT/scripts/fetch_models.sh" --verify >/dev/null \
    || { echo "prepare_space: backend/models is missing files or does not match the pins" >&2; exit 1; }
else
  excludes+=(--exclude 'backend/models/*')
fi

# rsync applies the first matching rule, so the --include lines must come before the
# broader --exclude lines they carve out of.
rsync -a --include '.env.example' --include 'backend/models/.gitkeep' "${excludes[@]}" "$ROOT/" "$OUT/"
cp "$ROOT/deploy/huggingface/README.md" "$OUT/README.md"

echo "prepare_space: Space files are in $OUT"
echo "  README.md is the Space card (it links to https://github.com/teameuphoriainv-dot/solace-cac)."
[ "$WITH_MODELS" -eq 1 ] && echo "  Model files included: push with git-xet or git-lfs installed."
echo "Next: follow deploy/DEPLOY.md, step 5."
