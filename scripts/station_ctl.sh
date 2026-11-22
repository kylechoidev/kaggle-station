#!/usr/bin/env bash
# station_ctl.sh - control a running Kaggle station from the home computer (kaggle CLI + python3 only).
#
# Run state:
#   station_ctl.sh status   <OWNER>/<KERNEL>             kaggle kernels status
#   station_ctl.sh logs     <OWNER>/<KERNEL> [-f]        kaggle kernels logs; -f streams the running session
#                                                        (CLI 2.2.5; without -f: empty until the run ends, docs/06)
#   station_ctl.sh output   <OWNER>/<KERNEL> <DIR>       download the run output (after the run ends)
# Control file (a private dataset holding station_control.json; schema in docs/11_file_formats.md):
#   station_ctl.sh init-control <OWNER>/<CONTROL_DATASET> <DIR>   create DIR + the dataset (seq 1, no orders)
#   station_ctl.sh show      <DIR>                       print the local control file
#   station_ctl.sh send      <DIR> <WORKER|*> <TEXT...>  add a message (delivered once, by id)
#   station_ctl.sh deadline  <DIR> <ISO-UTC>             move the deadline (capped by MAX_HOURS in the kernel)
#   station_ctl.sh soft-stop <DIR> <ISO-UTC>             move the soft stop (STOP files)
#   station_ctl.sh stop-all  <DIR> on|off                soft stop everyone now / lift it
#   station_ctl.sh reset     <DIR>                       clear orders and messages (do this before a new run)
# Progress (optional outbox dataset the kernel versions; UNVERIFIED path, docs/06):
#   station_ctl.sh init-outbox <OWNER>/<OUTBOX_DATASET> <DIR>
#   station_ctl.sh progress    <OWNER>/<OUTBOX_DATASET> <DIR>
#
# Every control edit bumps "seq" and publishes a new dataset version. CTL_NO_UPLOAD=1 edits locally only.
# DATASET_LICENSE sets the license name in new dataset-metadata.json files (default: other).
set -euo pipefail

usage() { awk 'NR>1 && /^set -euo/{exit} NR>1' "$0"; exit 2; }
[ $# -ge 1 ] || usage
cmd=$1; shift
CF=station_control.json

need() { [ "$#" -ge "$1" ] || usage; }

meta() {   # meta <DIR> <ID>
  [[ $2 =~ ^[A-Za-z0-9_-]+/[A-Za-z0-9-]{6,50}$ ]] || { echo "dataset id must be <owner>/<slug>, slug 6-50 chars" >&2; exit 1; }
  printf '{\n  "title": "%s",\n  "id": "%s",\n  "licenses": [{"name": "%s"}]\n}\n' "${2#*/}" "$2" "${DATASET_LICENSE:-other}" > "$1/dataset-metadata.json"
}

edit() {   # edit <DIR> <python expression body operating on dict c>
  local dir=$1 body=$2; shift 2
  [ -f "$dir/$CF" ] || { echo "no $dir/$CF (run init-control first)" >&2; exit 1; }
  python3 -I - "$dir/$CF" "$@" <<PY
import datetime, json, sys
p = sys.argv[1]; a = sys.argv[2:]
c = json.load(open(p))
def utc(s):
    t = datetime.datetime.fromisoformat(s.replace('Z', '+00:00'))
    if t.tzinfo is None:
        sys.exit('give the time in UTC with a Z suffix, e.g. 2026-01-01T18:00:00Z')
    return t.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
$body
c['seq'] = int(c.get('seq', 0)) + 1
c['updated_utc'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
json.dump(c, open(p, 'w'), indent=1)
print('seq', c['seq'])
PY
  publish "$dir"
}

publish() {
  if [ "${CTL_NO_UPLOAD:-0}" = 1 ]; then echo "local only (CTL_NO_UPLOAD=1)"; return; fi
  kaggle datasets version -p "$1" -m "control seq $(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["seq"])' "$1/$CF")" -q
  echo "published; the kernel applies it at its next control poll (CONTROL_POLL_S)"
}

case $cmd in
  status) need 1 "$@"; kaggle kernels status "$1" ;;
  logs)
    need 1 "$@"
    case ${2:-} in -f|--follow) kaggle kernels logs -f "$1" ;; '') kaggle kernels logs "$1" ;; *) usage ;; esac ;;
  output) need 2 "$@"; mkdir -p "$2"; kaggle kernels output "$1" -p "$2" -o ;;
  init-control)
    need 2 "$@"; mkdir -p "$2"
    [ ! -e "$2/$CF" ] || { echo "$2/$CF exists" >&2; exit 1; }
    printf '{\n "schema": 1,\n "seq": 1,\n "deadline_utc": null,\n "soft_stop_utc": null,\n "stop_all": false,\n "messages": []\n}\n' > "$2/$CF"
    meta "$2" "$1"
    if [ "${CTL_NO_UPLOAD:-0}" = 1 ]; then echo "local only"; else kaggle datasets create -p "$2" -q; fi
    echo "control dataset $1 ready in $2; add it to dataset_sources and set CONTROL_DATASET in the kernel" ;;
  show) need 1 "$@"; cat "$1/$CF" ;;
  send)
    need 3 "$@"; dir=$1; to=$2; shift 2
    edit "$dir" "c.setdefault('messages', []).append({'id': 'm%d' % (int(c.get('seq', 0)) + 1), 'to': a[0], 'text': ' '.join(a[1:])})" "$to" "$@" ;;
  deadline)  need 2 "$@"; edit "$1" "c['deadline_utc'] = utc(a[0])" "$2" ;;
  soft-stop) need 2 "$@"; edit "$1" "c['soft_stop_utc'] = utc(a[0])" "$2" ;;
  stop-all)
    need 2 "$@"; case $2 in on|off) ;; *) usage ;; esac
    edit "$1" "c['stop_all'] = (a[0] == 'on')" "$2" ;;
  reset) need 1 "$@"; edit "$1" "c.update(deadline_utc=None, soft_stop_utc=None, stop_all=False, messages=[])" ;;
  init-outbox)
    need 2 "$@"; mkdir -p "$2"; meta "$2" "$1"
    printf '{"utc": null, "note": "placeholder until the station publishes"}\n' > "$2/status.json"
    if [ "${CTL_NO_UPLOAD:-0}" = 1 ]; then echo "local only"; else kaggle datasets create -p "$2" -q; fi
    echo "outbox dataset $1 created; set OUTBOX_DATASET in the kernel" ;;
  progress)
    need 2 "$@"; mkdir -p "$2"
    kaggle datasets download "$1" -p "$2" -o -q --unzip
    python3 -I -m json.tool "$2/status.json" ;;
  *) usage ;;
esac
