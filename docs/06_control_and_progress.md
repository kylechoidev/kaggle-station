# 06 - Control and progress with only a home computer

A Kaggle batch run accepts no inbound connections. Everything you send goes through Kaggle (datasets), and
everything you read comes back through Kaggle (status, logs, output, datasets).

## What works while a run is going

| Route | Direction | Result | Tag |
|---|---|---|---|
| `kaggle kernels status <OWNER>/<KERNEL_SLUG>` | up | `KernelWorkerStatus.RUNNING`, then a final state | MEASURED |
| `kaggle kernels logs <OWNER>/<KERNEL_SLUG>` (CLI 2.0.2 and 2.2.5, without `-f`) | up | nothing for the running version; after the end, the whole log as a JSON array of `{"stream_name", "time", "data"}` entries | MEASURED |
| `kaggle kernels logs -f <OWNER>/<KERNEL_SLUG>` (CLI 2.2.5: "Stream live execution logs from the running session") | up | **works**: plain text lines, `setup.log` lines and every `STATION {...}` line appeared within seconds; the command exits by itself when the run ends | MEASURED (2026-11-22 template run) |
| `kaggle kernels files` / `kaggle kernels output` | up | nothing until the run ends | MEASURED |
| Run output after the end | up | `/kaggle/working` contents plus `<KERNEL_SLUG>.log`; downloadable as soon as status is `COMPLETE`; each version's output stays downloadable by version (`kaggle kernels output <OWNER>/<KERNEL_SLUG>/<N>`) after later pushes | MEASURED |
| Attach a **new** dataset inside the run (`kagglehub.dataset_download`) | down | `New Datasets cannot be attached in non-interactive sessions` | MEASURED |
| Re-attach an already attached dataset (latest) | down | returns the existing mount | MEASURED |
| Attach a **newer version** of an attached dataset | down | not tried (a non-existent version number gave `Not found`); not needed, see the next row | UNVERIFIED |
| `kaggle datasets download` of the control dataset from inside the run (session auth, CLI 2.0.2, no `KAGGLE_JSON`) | down | **works**: the newest version (seq 3) was downloaded and applied 36 s after `station_ctl.sh` returned; deadline moved earlier and a message delivered | MEASURED |
| `kaggle datasets version` of an outbox dataset from inside the run (session auth, no `KAGGLE_JSON`) | up | **works**: `outbox version rc 0` five times, about 5 s each; `station_ctl.sh progress` at home read the new `status.json` | MEASURED |
| Cancel from the CLI | - | no such command; use the web UI | MEASURED (CLI) |
| rsync to your own server | both | worked; status arrived about 1 min after workers started; messages reached all 5 workers on consecutive 60 s passes | MEASURED (appendix A) |

**Without your own server, all three Kaggle-native channels work** (MEASURED in the 2026-11-22 template run, a 30-minute
CPU session with one shell worker and one Claude Code worker): `kernels logs -f` live, control dataset re-download,
outbox dataset versions. The session's built-in login was enough; no `KAGGLE_JSON` was needed. The station still
works fire-and-forget (level 0) if a channel fails on your account.

## Three levels

| Level | Setup | You get mid-run | Risk |
|---|---|---|---|
| 0 fire-and-forget | `CONTROL_DATASET = None`, `OUTBOX_DATASET = None` | `status` only; results at the end | none: everything decided before the push |
| 1 Kaggle-native control | control dataset attached and re-downloaded every `CONTROL_POLL_S`; optional outbox dataset and live logs | steer deadline, soft stop, messages; progress | MEASURED channels; if one fails on your account, the run behaves as level 0 |
| 2 own server | appendix A | live status and control every 60 s | needs a server; MEASURED |

Level 0 rules: keep runs short (1 to 3 h), read the output, adjust, push again. Choose `RUN_HOURS` and
`SOFT_STOP_LEAD_MIN` conservatively. They are fixed once the run starts unless level 1 works.

### Test level 1 once (30 min, one worker)

Measured result of this test (2026-11-22): `control: deadline ...` and `control: message m2 -> S1` at +3 min 5 s,
`outbox version rc 0` every 5 min, live `STATION` lines through `kernels logs -f`. Repeat it once on your own account.

1. `CONTROL_DATASET = '<OWNER>/<CONTROL_DATASET>'`, `CONTROL_POLL_S = 120`, `OUTBOX_DATASET = '<OWNER>/<OUTBOX_DATASET>'`,
   `OUTBOX_EVERY_S = 300`, `STDOUT_PROGRESS_S = 60`, `RUN_HOURS = 0.5`.
2. Push. When `status` says RUNNING: `scripts/station_ctl.sh send ./ctl W1 "test message"`.
3. Try `kaggle kernels logs -f <OWNER>/<KERNEL_SLUG>` and `scripts/station_ctl.sh progress <OWNER>/<OUTBOX_DATASET> ./outbox`.
4. After the end, check `out/setup.log`:

| Line in setup.log | Proves |
|---|---|
| `control: message m2 -> W1` | the down channel works (the session downloaded a newer dataset version) |
| `control download failed rc ...` | it does not, with this auth; add `KAGGLE_JSON` to the keys dataset and test again |
| `outbox version rc 0` | the up channel works |
| `outbox version rc 1 ...` | it does not; same fix, or stay at level 0 |

If your results differ, record them in your fork's docs.

## The control-file protocol

One JSON file, `station_control.json`, in a private control dataset. Schema: docs/11.

```json
{
 "schema": 1,
 "seq": 4,
 "deadline_utc": "2026-01-01T19:00:00Z",
 "soft_stop_utc": "2026-01-01T18:30:00Z",
 "stop_all": false,
 "messages": [
  {"id": "m2", "to": "W1", "text": "After this batch switch to slice 3. Replaces message m1."},
  {"id": "m3", "to": "*",  "text": "Close every claim before 18:30 UTC."}
 ],
 "updated_utc": "2026-01-01T16:02:11Z"
}
```

| When the kernel reads it | Source |
|---|---|
| once, before starting workers | the attached control dataset under `/kaggle/input` (`CONTROL_FILE`) |
| every `CONTROL_POLL_S` | `kaggle datasets download <CONTROL_DATASET> -f station_control.json -p /root/.station/control -o -q` (MEASURED: works with the session login) |
| every `LOOP_S` | appendix A: `rsync <RELAY_TARGET>:inbox/station_control.json` |

Semantics (`apply_control()`; unit-tested in `tests/test_station_kernel.py`):

| Field | Rule |
|---|---|
| `seq` | must be greater than the last applied `seq`, otherwise the whole document is ignored. `station_ctl.sh` bumps it on every edit. |
| `deadline_utc` | moves the deadline; **capped at start + `MAX_HOURS`**. If `soft_stop_utc` is absent, soft stop = deadline - `SOFT_STOP_LEAD_MIN`. |
| `soft_stop_utc` | moves the soft stop; capped at the deadline. |
| `stop_all` | `true`: STOP files now. `false` after a station-written STOP, with the soft stop in the future: the station removes its own STOP files (it never removes a STOP that a worker or you wrote). |
| `messages[]` | each `id` is delivered once per run, appended to `agents/<to>/INBOX.md`; `to` is a worker name or `*`. Unknown names are logged as `-> nobody`. |
| times | ISO 8601. `station_ctl.sh` refuses times without a zone; the kernel treats zone-less times as UTC. |
| unreadable document | logged as `bad control document`, ignored; the run continues |

### Sending (home)

```bash
scripts/station_ctl.sh send      ./ctl W1 "text"          # or '*' for everyone
scripts/station_ctl.sh deadline  ./ctl 2026-01-01T19:00:00Z
scripts/station_ctl.sh soft-stop ./ctl 2026-01-01T18:30:00Z
scripts/station_ctl.sh stop-all  ./ctl on                 # off lifts a station STOP
scripts/station_ctl.sh reset     ./ctl                    # before the next run
scripts/station_ctl.sh show      ./ctl
```

Each edit publishes a dataset version (`kaggle datasets version -p ./ctl -m "control seq N" -q`).

Latency, end to end: dataset processing (MEASURED: `ready` a few seconds after `station_ctl.sh` returned), plus up
to `CONTROL_POLL_S`, plus the worker's next batch boundary (minutes). Measured with `CONTROL_POLL_S = 120`: published
16:17:21, applied 16:17:57, read by the shell worker 16:18:02. A successful download of an unchanged `seq` logs nothing.

Message hygiene (learned in the measured run):

| Rule | Reason |
|---|---|
| Use absolute UTC times | agents re-read the whole INBOX and need unambiguous times |
| Say what a message replaces ("Replaces message m2") | otherwise the agent has to guess which instruction wins |
| Give the exact wind-down sequence: "after T1 start nothing new; finish the batch in flight; have everything closed before T2" | worked |
| Do not put a deadline in a message when you can move it in the control file | in the measured run the stop time was compiled into the kernel. When the operator moved it, every agent had to be told to *ignore* its STOP file. That worked, but it was fragile. |
| Control content is a prompt to agents with root and your credentials | only you may be able to write the control dataset |

## Progress back (up channel)

| Source | What | Setting | Tag |
|---|---|---|---|
| `kaggle kernels status` | state only | - | MEASURED |
| stdout | `STATION {"utc":..., "deadline_utc":..., "soft_stop_utc":..., "load":[...], "alive":[...]}` every `STDOUT_PROGRESS_S` | default 300 s | live with `kaggle kernels logs -f` (CLI 2.2.5) or `station_ctl.sh logs <KERNEL> -f`: MEASURED |
| outbox dataset | `status.json` (docs/11), new version every `OUTBOX_EVERY_S` with `-d` (delete old versions) | `OUTBOX_DATASET` | MEASURED (session login, `OUTBOX_EVERY_S = 300`) |
| run output | `out/status.json`, refreshed every `LOOP_S`; final copy has `"final": true` | always | after the end |
| snapshots | `out/results.tar.gz` every `SNAPSHOT_EVERY_S` | default 1800 s | after the end |

Keep the outbox small. Every version is stored, and frequent versions may hit rate limits (UNVERIFIED). Never put
worker logs or private inputs in it.
