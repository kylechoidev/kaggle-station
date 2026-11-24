#!/usr/bin/env bash
# swarm/kaggle/make_code_bundle.sh OWNER/DATASET PROVIDERS_JSON [--create]
# Packs swarm/ plus a providers file (key PATHS only, no keys) into swarm_code.tgz.bin and uploads it as a private
# Kaggle dataset (new version, or --create the first time). Keys go in a separate dataset: scripts/make_keys_dataset.sh.
set -euo pipefail
DS=${1:?usage: make_code_bundle.sh OWNER/DATASET PROVIDERS_JSON [--create]}; PJ=${2:?providers json}
cd "$(dirname "$0")/../.."
if grep -qiE '"key"[[:space:]]*:[[:space:]]*"[A-Za-z0-9_-]{24,}"' "$PJ"; then echo "REFUSED: $PJ looks like it holds a key, not a key path"; exit 1; fi
T=$(mktemp -d); mkdir -p "$T/stage/hub" "$T/ds"
cp -r swarm "$T/stage/"; cp "$PJ" "$T/stage/hub/providers.json"
find "$T/stage" -name '__pycache__' -prune -exec rm -rf {} +
tar -C "$T/stage" -czf "$T/ds/swarm_code.tgz.bin" swarm hub
printf '{"title": "%s", "id": "%s", "licenses": [{"name": "CC0-1.0"}]}\n' "${DS#*/}" "$DS" > "$T/ds/dataset-metadata.json"
if [ "${3:-}" = --create ]; then kaggle datasets create -p "$T/ds" -q; else kaggle datasets version -p "$T/ds" -m "swarm code $(date -u +%FT%TZ)" -q; fi
echo "uploaded $DS ($(du -h "$T/ds/swarm_code.tgz.bin" | cut -f1))"; rm -rf "$T"
