#!/usr/bin/env bash
# Downloads the trained bedside triage model into backend/models.
#
# The model is 5 LightGBM folds, artifacts.pkl (the feature setup) and conformal.pkl (the
# likely-range calibrator), about 250 MB in all, too big for git.
# It lives as one tarball on a GitHub Release. Every file is checked against the
# SHA-256 pinned below before it is installed. The .pkl files are Python pickles, and
# loading a tampered pickle can run code, so a mismatch is a hard stop, not a warning.
#
# Usage (from anywhere):
#   scripts/fetch_models.sh            install, or do nothing if already installed
#   scripts/fetch_models.sh --verify   only check what is installed (exit 0 ok, 1 mismatch, 2 missing)
#   scripts/fetch_models.sh --force    replace local files that do not match the pins
#
# Settings (environment variables, all optional):
#   SOLACE_MODELS_REPO  GitHub repo that holds the release  (default teameuphoriainv-dot/solace-cac)
#   SOLACE_MODELS_TAG   release tag                          (default models-v1)
#   SOLACE_MODELS_URL   tarball URL or local path; skips GitHub (file:///path/x.tar.gz works)
#   SOLACE_MODELS_DIR   install folder                       (default backend/models)
#   SOLACE_MODELS_SHA256  expected tarball sha256 (default pinned below; the per-file pins still apply)
#
# Without the model the app still runs: triage falls back to the deterministic rules.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="${SOLACE_MODELS_REPO:-teameuphoriainv-dot/solace-cac}"
TAG="${SOLACE_MODELS_TAG:-models-v1}"
ASSET="solace-models-v1.tar.gz"
URL="${SOLACE_MODELS_URL:-}"
DEST="${SOLACE_MODELS_DIR:-$ROOT/backend/models}"

TARBALL_SHA256="${SOLACE_MODELS_SHA256:-bb76713729aac4edb576a501c695f1b965d33a27fc4abc8959b166bcbe19036f}"

# sha256  filename   (shasum -a 256 backend/models/* to regenerate after a retrain or after
# re-running scripts/calibrate_conformal.py, which writes a new conformal.pkl)
MANIFEST="\
1b61d804c3e45a006c6c9e686305f2e23f1b0af105252f2bad3202110703816f  artifacts.pkl
d662020e2bcc82f6e072f1d94fa523625315ff5b035a8198b392dc87e99f0468  conformal.pkl
26518b73e77425e5075b6087d6c5e039d8cd6976807002b1d0d85d30021e159f  lgbm_fold0.txt
8e5e3668c214d4e0e73e5b2bf45f11d04723451b3842d3dbd7cc1797702bfac5  lgbm_fold1.txt
95206f6a509b87c02a78c6f7c701db3d5a1c792e892a2a993635b79dbe4be5d6  lgbm_fold2.txt
3bb3885b983e56acb06f2800c60659b39c407cefea9a652f82d5a49352ce5475  lgbm_fold3.txt
06b6c6ec015ec1eacef41e9dfa7c60157910c25c0ebf57567cb6cd4b6aa512e4  lgbm_fold4.txt"

MODE="install"
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --verify) MODE="verify" ;;
    --force) FORCE=1 ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "fetch_models: unknown option $arg (try --help)" >&2; exit 64 ;;
  esac
done

say() { echo "fetch_models: $*"; }
die() { echo "fetch_models: $*" >&2; exit 1; }

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    python3 -c 'import hashlib,sys
h=hashlib.sha256()
with open(sys.argv[1],"rb") as f:
    for b in iter(lambda: f.read(1<<20), b""): h.update(b)
print(h.hexdigest())' "$1"
  fi
}

# Prints one line per pinned file: ok, missing or bad. Returns 0 / 2 / 1 like --verify.
check_dir() {
  local dir="$1" rc=0 want name got
  while read -r want name; do
    [ -n "$name" ] || continue
    if [ ! -e "$dir/$name" ]; then
      echo "  missing  $name"
      [ "$rc" -eq 1 ] || rc=2
    elif [ -L "$dir/$name" ] || [ ! -f "$dir/$name" ]; then
      echo "  bad      $name (not a regular file)"
      rc=1
    else
      got="$(sha256_of "$dir/$name")"
      if [ "$got" = "$want" ]; then
        echo "  ok       $name"
      else
        echo "  bad      $name (sha256 $got, expected $want)"
        rc=1
      fi
    fi
  done <<EOF
$MANIFEST
EOF
  return "$rc"
}

installed_rc=0
report="$(check_dir "$DEST")" || installed_rc=$?

if [ "$MODE" = "verify" ]; then
  echo "$report"
  case "$installed_rc" in
    0) say "all model files in $DEST match the pinned hashes." ;;
    2) say "some model files are missing from $DEST. Run scripts/fetch_models.sh to download them." ;;
    *) say "some files in $DEST do NOT match the pinned hashes. Do not load them." ;;
  esac
  exit "$installed_rc"
fi

if [ "$installed_rc" -eq 0 ]; then
  say "model already installed in $DEST, nothing to do."
  exit 0
fi
if [ "$installed_rc" -eq 1 ] && [ "$FORCE" -ne 1 ]; then
  echo "$report"
  die "files in $DEST do not match the pinned hashes (a retrained model?). Move them away or re-run with --force to replace them."
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/solace-models.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
TARBALL="$WORK/$ASSET"

if [ -n "$URL" ]; then
  case "$URL" in
    file://*) src="${URL#file://}"; say "copying $src"; cp "$src" "$TARBALL" ;;
    http://*|https://*) say "downloading $URL"; curl -fL --retry 3 --progress-bar -o "$TARBALL" "$URL" ;;
    *) say "copying $URL"; cp "$URL" "$TARBALL" ;;
  esac
else
  got_it=0
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    say "downloading $ASSET from $REPO release $TAG with gh"
    if gh release download "$TAG" --repo "$REPO" --pattern "$ASSET" --dir "$WORK" --clobber; then
      got_it=1
    else
      say "gh download failed, trying curl"
    fi
  fi
  if [ "$got_it" -ne 1 ]; then
    command -v curl >/dev/null 2>&1 || die "need gh or curl to download the model"
    url="https://github.com/$REPO/releases/download/$TAG/$ASSET"
    say "downloading $url"
    curl -fL --retry 3 --progress-bar -o "$TARBALL" "$url" \
      || die "download failed. Check that release $TAG exists on $REPO and is public, or set SOLACE_MODELS_URL."
  fi
fi

[ -s "$TARBALL" ] || die "the downloaded file is empty"

got="$(sha256_of "$TARBALL")"
[ "$got" = "$TARBALL_SHA256" ] \
  || die "tarball sha256 is $got, expected $TARBALL_SHA256. Refusing to unpack it."

# Only unpack the exact file names we expect: no folders, no '..', nothing else.
allowed="$(printf '%s\n' "$MANIFEST" | awk 'NF {print $2}')"
while read -r member; do
  [ -n "$member" ] || continue
  printf '%s\n' "$allowed" | grep -qxF -- "$member" \
    || die "unexpected entry '$member' in the tarball. Refusing to unpack it."
done <<EOF
$(tar -tzf "$TARBALL")
EOF

mkdir -p "$WORK/out"
tar -xzf "$TARBALL" -C "$WORK/out" --no-same-owner
rm -f "$TARBALL"

say "checking every file"
if ! check_dir "$WORK/out"; then
  die "a file inside the tarball does not match its pinned hash. Nothing was installed."
fi

mkdir -p "$DEST"
while read -r _ name; do
  [ -n "$name" ] || continue
  rm -f "$DEST/$name"
  mv "$WORK/out/$name" "$DEST/$name"
done <<EOF
$MANIFEST
EOF

say "installed the triage model into $DEST"
