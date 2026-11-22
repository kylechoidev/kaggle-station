#!/usr/bin/env bash
# push_kernel.sh - write kernel-metadata.json and push station_kernel.py as a private, internet-enabled CPU
# script kernel. A push starts a new run (version) immediately.
#
# usage: push_kernel.sh <OWNER>/<KERNEL_SLUG> <OWNER>/<DATASET> [<OWNER>/<DATASET> ...]
#   list every dataset the run needs: kit archive(s), keys, control (all private).
# env:
#   KERNEL_FILE  kernel source (default: station_kernel.py next to this script)
#   TIMEOUT_S    per-run limit passed as `kaggle kernels push -t` (the platform maximum still applies)
#   STAGE_DIR    keep the generated folder here instead of a temp dir (for review)
#   DRY_RUN=1    write and print the metadata, do not push
#   FORCE=1      push even if `kaggle kernels status` says the kernel is running or queued. The running version
#                keeps running in parallel (MEASURED); `status` then reports only the newest version.
set -euo pipefail
[ $# -ge 2 ] || { awk 'NR>1 && /^set -euo/{exit} NR>1' "$0"; exit 2; }
ID=$1; shift
SLUG=${ID#*/}
[[ $ID =~ ^[A-Za-z0-9_-]+/[a-z0-9-]{5,50}$ ]] || { echo "kernel id must be <owner>/<slug>, slug 5-50 chars of a-z 0-9 -" >&2; exit 1; }
for d in "$@"; do [[ $d =~ ^[A-Za-z0-9_-]+/[A-Za-z0-9_-]+$ ]] || { echo "bad dataset id: $d" >&2; exit 1; }; done
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=${KERNEL_FILE:-$HERE/station_kernel.py}
[ -f "$SRC" ] || { echo "kernel file not found: $SRC" >&2; exit 1; }
if [ -n "${STAGE_DIR:-}" ]; then STAGE=$STAGE_DIR; mkdir -p "$STAGE"; else STAGE=$(mktemp -d); trap 'rm -rf "$STAGE"' EXIT; fi
cp "$SRC" "$STAGE/station_kernel.py"
DS=$(printf '"%s", ' "$@"); DS="[${DS%, }]"
cat > "$STAGE/kernel-metadata.json" <<JSON
{
  "id": "$ID",
  "title": "$SLUG",
  "code_file": "station_kernel.py",
  "language": "python",
  "kernel_type": "script",
  "is_private": true,
  "enable_gpu": false,
  "enable_tpu": false,
  "enable_internet": true,
  "dataset_sources": $DS,
  "competition_sources": [],
  "kernel_sources": [],
  "model_sources": []
}
JSON
python3 -I -m json.tool "$STAGE/kernel-metadata.json" >/dev/null
cat "$STAGE/kernel-metadata.json"
[ "${DRY_RUN:-0}" = 1 ] && { echo "dry run: not pushed"; exit 0; }
if [ "${FORCE:-0}" != 1 ]; then
  st=$(kaggle kernels status "$ID" 2>&1 || true)
  if grep -Eqi 'running|queued' <<<"$st"; then
    echo "refusing: $st  (wait for it to finish, or FORCE=1)" >&2; exit 1
  fi
fi
args=(kernels push -p "$STAGE")
[ -n "${TIMEOUT_S:-}" ] && args+=(-t "$TIMEOUT_S")
kaggle "${args[@]}"
echo "status:  kaggle kernels status $ID"
echo "output:  kaggle kernels output $ID -p ./run_output -o   (after the run ends)"
