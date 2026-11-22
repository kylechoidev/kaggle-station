#!/usr/bin/env bash
# make_keys_dataset.sh - upload credentials as files in a SEPARATE private Kaggle dataset (docs/02).
#
# usage: make_keys_dataset.sh <OWNER>/<KEYS_DATASET> NAME=path/to/file [NAME=path ...]
#   e.g. make_keys_dataset.sh <OWNER>/<KEYS_DATASET> CLAUDE_CODE_OAUTH_TOKEN=./claude_token.txt
# Each file is stored under NAME; the kernel looks credentials up by that name. Values are never printed.
# env: CTL_NO_UPLOAD=1 stage only (prints the staging dir; delete it yourself)
#      DATASET_LICENSE license name in dataset-metadata.json (default: other)
#
# Exposure: anyone signed in to this Kaggle account (and any process in a run that attaches the dataset)
# can read these files. Kaggle keeps every dataset version: to rotate, revoke the old credential, delete the
# dataset (kaggle datasets delete <OWNER>/<KEYS_DATASET> -y) and run this script again.
set -euo pipefail
[ $# -ge 2 ] || { awk 'NR>1 && /^set -euo/{exit} NR>1' "$0"; exit 2; }
ID=$1; shift
[[ $ID =~ ^[A-Za-z0-9_-]+/[A-Za-z0-9-]{6,50}$ ]] || { echo "dataset id must be <owner>/<slug>, slug 6-50 chars" >&2; exit 1; }
umask 077
STAGE=$(mktemp -d)
[ "${CTL_NO_UPLOAD:-0}" = 1 ] || trap 'rm -rf "$STAGE"' EXIT
for kv in "$@"; do
  n=${kv%%=*}; f=${kv#*=}
  [[ $n =~ ^[A-Z0-9_]+$ ]] || { echo "bad name (use A-Z 0-9 _): $n" >&2; exit 1; }
  [ -s "$f" ] || { echo "missing or empty: $f" >&2; exit 1; }
  tr -d '\r' < "$f" > "$STAGE/$n"
  echo "staged $n ($(wc -c < "$STAGE/$n") bytes)"
done
printf '{\n  "title": "%s",\n  "id": "%s",\n  "licenses": [{"name": "%s"}]\n}\n' "${ID#*/}" "$ID" "${DATASET_LICENSE:-other}" > "$STAGE/dataset-metadata.json"
if [ "${CTL_NO_UPLOAD:-0}" = 1 ]; then echo "staged in $STAGE (not uploaded)"; exit 0; fi
kaggle datasets create -p "$STAGE" -q        # private: no --public
echo "created private dataset $ID; wait for: kaggle datasets status $ID  -> ready"
