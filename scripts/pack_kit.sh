#!/usr/bin/env bash
# pack_kit.sh - pack a directory into a zstd tarball and optionally upload it as a PRIVATE Kaggle dataset.
#
# usage: pack_kit.sh <SRC_DIR> <ARCHIVE.tar.zst> <DATASET_DIR> [--upload <OWNER>/<DATASET>]
#   SRC_DIR      packed relative to its parent: the archive's top folder is basename(SRC_DIR)
#   DATASET_DIR  local staging folder; the archive, its .sha256 and dataset-metadata.json are written here
#   --upload     create the dataset on first use, publish a new version afterwards
# env: EXCLUDES="glob ..."  extra tar --exclude patterns     ZSTD_LEVEL (default 12)     THREADS (default 0 = all)
#      DATASET_LICENSE  license name for a new dataset-metadata.json (default: other)
#
# Refuses (and deletes the archive) if any path looks like a credential. Decide BEFORE uploading what may
# leave your machine (docs/03): a private dataset is still stored by a third party.
set -euo pipefail
[ $# -ge 3 ] || { awk 'NR>1 && /^set -euo/{exit} NR>1' "$0"; exit 2; }
SRC=$(realpath "$1"); ARCH=$2; DS=$3; shift 3
UPLOAD=""
if [ "${1:-}" = "--upload" ]; then UPLOAD=${2:?dataset id <OWNER>/<DATASET>}; fi
if [ -n "$UPLOAD" ] && ! [[ $UPLOAD =~ ^[A-Za-z0-9_-]+/[A-Za-z0-9-]{6,50}$ ]]; then
  echo "dataset id must be <owner>/<slug>, slug 6-50 chars" >&2; exit 1
fi
[ -d "$SRC" ] || { echo "not a directory: $SRC" >&2; exit 1; }
[[ $ARCH == *.tar.zst ]] || { echo "archive name must end in .tar.zst" >&2; exit 1; }
command -v zstd >/dev/null || { echo "zstd not found (Debian/Ubuntu: apt install zstd)" >&2; exit 1; }
mkdir -p "$DS"
ex=(--exclude='*.pyc' --exclude='__pycache__' --exclude='.git' --exclude='*.key' --exclude='*.pem' --exclude='.env')
read -r -a extra <<< "${EXCLUDES:-}"
for p in "${extra[@]}"; do ex+=(--exclude="$p"); done
echo "packing $SRC -> $DS/$ARCH"
t0=$(date +%s)
tar -C "$(dirname "$SRC")" "${ex[@]}" -cf - "$(basename "$SRC")" | zstd -q "-${ZSTD_LEVEL:-12}" "-T${THREADS:-0}" -f -o "$DS/$ARCH"
echo "raw $(du -sh "$SRC" | cut -f1), archive $(du -h "$DS/$ARCH" | cut -f1), $(( $(date +%s) - t0 )) s"
if zstd -dc "$DS/$ARCH" | tar -tf - | grep -Ei '(id_rsa|id_ed25519|\.pem$|\.key$|api_key|credentials|\.env$|oauth|token|kaggle\.json)'; then
  rm -f "$DS/$ARCH"
  echo "REFUSING: credential-looking paths (listed above); archive deleted. Add EXCLUDES and re-run." >&2
  exit 1
fi
(cd "$DS" && sha256sum "$ARCH" > "$ARCH.sha256" && cat "$ARCH.sha256")
[ -n "$UPLOAD" ] || exit 0
if [ ! -f "$DS/dataset-metadata.json" ]; then
  printf '{\n  "title": "%s",\n  "id": "%s",\n  "licenses": [{"name": "%s"}]\n}\n' "${UPLOAD#*/}" "$UPLOAD" "${DATASET_LICENSE:-other}" > "$DS/dataset-metadata.json"
  kaggle datasets create -p "$DS" -q          # private unless --public is given
else
  kaggle datasets version -p "$DS" -m "kit $(date -u +%FT%TZ)" -q
fi
echo "uploaded; wait for: kaggle datasets status $UPLOAD  -> ready"
