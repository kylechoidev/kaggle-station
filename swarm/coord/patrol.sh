#!/usr/bin/env bash
# swarm/coord/patrol.sh - trigger-only coordinator loop (run in tmux on a host the hub copies status to).
# A cheap shell loop: every 5 min it reads $SWARM_ROOT/hub/status.json and hub/hosts/*.json and calls the model ONLY
# when a trigger fires; the model does one patrol (brief: swarm/coord/brief_template.md, copied to hub/coord/brief.md
# and filled in), writes hub/coord/log.md, and exits.
#   Triggers: new alert line; a watched worker down > 15 min with a "not restarted"/"cap"/"held" decision; the
#   VERIFIER_STALE flag on a host > 30 min; hub status older than 20 min; LLM_DEAL_ENDED / LLM_COST; routine every
#   ROUTINE_H hours. Same trigger set at most once an hour; at most MAX_PER_DAY model calls per UTC day.
#   Handback: when a push-only host (the owner's laptop) reported in the last 15 min, run one last patrol that writes
#   hub/coord/HANDBACK.md, then make no model calls until it is gone again.
# Env: COORD_CMD (default: Claude Code headless, below; any CLI that takes the prompt on stdin works),
#      COORD_DRY=1 (echo instead of calling the model), MAX_PER_DAY (8), ROUTINE_H (6), PATROL_TIMEOUT (2400 s).
# Stop: touch $SWARM_ROOT/hub/COORD_STOP
set -u
ROOT=${SWARM_ROOT:-$(pwd)}; H=$ROOT/hub; C=$H/coord; mkdir -p "$C" "$H/requests"
MAX=${MAX_PER_DAY:-8}; RH=${ROUTINE_H:-6}; PT=${PATROL_TIMEOUT:-2400}
DEFAULT_CMD='claude -p --model opus --effort medium --permission-mode acceptEdits --allowedTools Bash,Read,Write,Edit,Glob,Grep --max-budget-usd 5 --output-format text'
CMD=${COORD_CMD:-$DEFAULT_CMD}; [ "${COORD_DRY:-0}" = 1 ] && CMD='cat'
BRIEF=$C/brief.md; [ -f "$BRIEF" ] || BRIEF=$ROOT/swarm/coord/brief_template.md
say() { echo "$(date -u +%FT%TZ) $*" >> "$C/patrol.log"; }
say "patrol loop start (pid $$, max $MAX/day, routine ${RH}h, dry ${COORD_DRY:-0})"
RAN=0
while :; do
  [ -f "$H/COORD_STOP" ] && { say "COORD_STOP: exit"; exit 0; }
  TRIG=$(python3 -I "$ROOT/swarm/coord/triggers.py" "$H" "$RH")
  if [ "$TRIG" = OWNER_PRESENT ]; then
    if [ "$RAN" = 1 ] && [ ! -f "$C/HANDBACK.done" ]; then TRIG="the owner's host is back: write hub/coord/HANDBACK.md and exit"; touch "$C/HANDBACK.done"
    else sleep 300; continue; fi
  else rm -f "$C/HANDBACK.done"; fi
  if [ -n "$TRIG" ]; then
    day=$(date -u +%F); n=$(cat "$C/count_$day" 2>/dev/null || echo 0)
    if [ "$n" -ge "$MAX" ]; then say "trigger skipped (daily cap): $TRIG"
    else
      echo $((n+1)) > "$C/count_$day"; RAN=1; say "patrol $((n+1)): $TRIG"
      out="$C/patrol_$(date -u +%Y%m%dT%H%M%SZ).out"
      # shellcheck disable=SC2086
      { cat "$BRIEF"; printf '\n\nTRIGGER: %s\nUTC now: %s\n' "$TRIG" "$(date -u +%FT%TZ)"; } | (cd "$ROOT" && timeout "$PT" $CMD) > "$out" 2>&1
      say "patrol $((n+1)) end rc $?"
    fi
  fi
  sleep 300
done
