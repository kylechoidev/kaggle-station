#!/usr/bin/env bash
# swarm/hub/push_host.sh HUB_SSH HUB_ROOT - for a host the hub cannot reach (a laptop): run from a timer every 5 min.
# Pulls config/providers, runs host.py tick, pushes its report (= heartbeat) and ledger export to the hub, pulls the
# merged ledger, status page and coordinator logs. Config: mark this host "push_only": true in hub/config.json.
#   systemd user timer example: docs/12_free_model_swarm.md, section "Quickstart".
set -u
HUB_SSH=${1:?usage: push_host.sh HUB_SSH HUB_ROOT}; HUB_ROOT=${2:?usage: push_host.sh HUB_SSH HUB_ROOT}
ROOT=${SWARM_ROOT:-$(pwd)}; H=$ROOT/hub; export SWARM_ROOT=$ROOT
mkdir -p "$H/hosts" "$H/ledger" "$H/coord" "$H/log"
exec 9>"$H/.push.lock"; flock -n 9 || exit 0
R=(rsync -a --timeout=60)
"${R[@]}" "$HUB_SSH:$HUB_ROOT/hub/config.json" "$H/" 2>>"$H/log/push.err" || { echo "$(date -u +%FT%TZ) hub unreachable" >> "$H/log/push.err"; exit 0; }
"${R[@]}" --ignore-missing-args "$HUB_SSH:$HUB_ROOT/hub/providers.json" "$H/" 2>>"$H/log/push.err"
me=$(python3 -I "$ROOT/swarm/hub/host.py" tick | python3 -c 'import json,sys; print(json.loads(sys.stdin.read().strip().splitlines()[-1])["host"])')
"${R[@]}" "$H/hosts/$me.json" "$HUB_SSH:$HUB_ROOT/hub/hosts/"
"${R[@]}" --mkpath "$H/outgoing/" "$HUB_SSH:$HUB_ROOT/hub/incoming/$me/"
"${R[@]}" "$HUB_SSH:$HUB_ROOT/hub/ledger/" "$H/ledger/"
"${R[@]}" --ignore-missing-args "$HUB_SSH:$HUB_ROOT/hub/status.json" "$HUB_SSH:$HUB_ROOT/hub/www" "$H/" 2>/dev/null
"${R[@]}" "$HUB_SSH:$HUB_ROOT/hub/coord/" "$H/coord/" 2>/dev/null
exit 0
