#!/usr/bin/env bash
# load_sampler.sh [OUT.tsv] [INTERVAL_S] - light CPU/RAM sampler (one TSV line per interval, runs forever).
# Start from SETUP_SHELL or a worker:  nohup bash scripts/load_sampler.sh /kaggle/working/out/load.tsv 180 &
# env: HEAVY_PATTERN  pgrep -f pattern counted as "heavy" processes (default: compilers)
set -u
out=${1:-/kaggle/working/out/load.tsv}
iv=${2:-180}
[ "$iv" -gt 5 ] || iv=6
cpu() {   # prints "idle_jiffies total_jiffies" from the first line of /proc/stat
  local _ u n s i w q sq st
  read -r _ u n s i w q sq st _ < /proc/stat
  echo "$(( i + w )) $(( u + n + s + i + w + q + sq + st ))"
}
if ! { mkdir -p "$(dirname "$out")" && touch "$out"; } 2>/dev/null; then echo "cannot write $out" >&2; exit 1; fi
[ -s "$out" ] || printf 'utc\tload1\tload5\tload15\tcpu_busy_pct\tmem_used_MiB\tmem_avail_MiB\tclaude_procs\theavy_procs\n' > "$out"
while true; do
  read -r l1 l5 l15 _ < /proc/loadavg
  read -r i1 t1 <<< "$(cpu)"
  sleep 5
  read -r i2 t2 <<< "$(cpu)"
  dt=$(( t2 - t1 )); [ "$dt" -gt 0 ] || dt=1
  busy=$(( 100 * (dt - (i2 - i1)) / dt ))
  read -r mu ma <<< "$(free -m | awk '/^Mem:/{print $3, $7}')"
  nc=$(pgrep -xc claude || true)
  nh=$(pgrep -fc "${HEAVY_PATTERN:-cc1|cl.exe|clang|gcc|make}" || true)
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$(date -u +%H:%M:%S)" "$l1" "$l5" "$l15" "$busy" "$mu" "$ma" "$nc" "$nh" >> "$out"
  sleep $(( iv - 5 ))
done
