# 09 - Shutdown and results

## Four layers of stop

| Layer | Default time | Mechanism | Changeable mid-run | Who acts |
|---|---|---|---|---|
| soft stop | deadline - `SOFT_STOP_LEAD_MIN` (20 min), or `soft_stop_utc`, or `stop_all` | station writes `agents/<N>/STOP` (content starts with `station`) | yes, control file | the worker at its next batch boundary: nothing new, finish or release, REPORT.md, exit |
| deadline | start + `RUN_HOURS`, or `deadline_utc` (capped) | control loop: SIGTERM to each worker's process group, SIGKILL after `KILL_GRACE_S` (90 s) | yes, control file, up to the cap | the OS |
| cap | start + `MAX_HOURS` | `timeout -k 30 <cap_s>` around each worker | no (fixed at worker start) | the OS, rc 124 |
| platform | session limit (12 h CPU per Kaggle docs, UNVERIFIED) or `push -t` | Kaggle kills the container | no | Kaggle |

Order of events at the end:

```
soft stop  -> STOP files                         (workers wind down)
all workers exited, or deadline -> SIGTERM -> +90 s SIGKILL
loop ends  -> results.tar.gz (allow-list) -> final status.json ("final": true) -> outbox / relay push -> "done"
```

Choose the soft-stop lead so the slowest in-flight item finishes. In the measured project, a claim left open at
kill time stayed locked for about an hour, so the brief required every claim to be closed before the hard stop.
Choose `MAX_HOURS` so packing finishes before the platform stop.

## Lesson from the measured run

The measured kernel had its stop time and the hard `timeout` compiled in. When the operator moved the stop time
after launch, the only option was to send messages telling every agent to ignore its STOP file and keep going
until a given UTC time. The hard `timeout` could not be extended at all. Hence this design: deadline and soft stop
live in the control file, and only the generous cap is fixed.

With level 0 (no live control, docs/06), nothing can change after the push. Choose times conservatively and keep
runs short.

## Results

| File in `/kaggle/working/out/` | Written | Content |
|---|---|---|
| `setup.log` | continuously | every station step with timings; credential names only |
| `status.json` | every `LOOP_S`; final copy with `"final": true` | docs/11 |
| `gate_station.json` | after the gate | the station's verdicts, for a diff against the reference |
| `logs/<NAME>.log` | continuously | worker stdout and stderr (stream-json for Claude Code); may contain private inputs |
| `results.tar.gz` | every `SNAPSHOT_EVERY_S` (1800 s) and at the end | allow-listed results (docs/03), paths relative to `WORKDIR` |

A snapshot survives if the container is killed before the end. The measured kernel packed only at the end; its
relay copies were the only insurance.

```bash
scripts/station_ctl.sh status <OWNER>/<KERNEL_SLUG>          # wait for a final state
scripts/station_ctl.sh output <OWNER>/<KERNEL_SLUG> ./run_output
```

What is discarded when the run ends (UNVERIFIED, per Kaggle docs; consistent with what we saw): everything outside
`/kaggle/working`, including the unpacked kit, installed packages, the Claude Code install and `~/.claude`.
Only datasets and the outputs of earlier versions persist. Earlier outputs can be attached as `kernel_sources`.

## After the run

| Step | Why |
|---|---|
| `status.json`: `final` true? every worker's `rc`? | `final` missing means the container died before the end; use the last snapshot |
| `grep -E 'GATE|PROBE|FAILED|error' run_output/out/setup.log` | setup problems |
| `python3 -I scripts/stream_summary.py run_output/out/logs/*.log` | per-worker tool use and rate-limit state, without content |
| unpack results with `filter="data"` into an empty directory | outputs are untrusted (docs/SECURITY.md) |
| verify every claimed result with your authoritative check | the station never self-certifies |
| fold durable lessons from `LESSONS.md` into the next brief | - |
| `scripts/station_ctl.sh reset ./ctl` | the next run would otherwise re-read old orders |
| delete or rotate keys at the end of a campaign | docs/02 |
