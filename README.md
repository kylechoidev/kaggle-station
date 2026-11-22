# Kaggle station

Run several long-lived worker processes, such as headless Claude Code agents, on one Kaggle CPU session.
You steer them from a home computer using only the `kaggle` CLI. Written for compile-and-check work like a
**decompilation project**, but the kernel runs any command.

**Typical setup: a home computer and a Kaggle account. Nothing else.** If you have your own server, an optional
live relay is described in [appendix A](docs/appendix_A_own_server_relay.md).

```
HOME COMPUTER (kaggle CLI, python3, zstd)                 KAGGLE CPU SESSION (batch run, internet on)
-----------------------------------------                 -------------------------------------------
pack_kit.sh        --- private dataset: kit -----------> /kaggle/input/**/kit_*.tar.zst
make_keys_dataset  --- private dataset: keys ----------> /kaggle/input/**/CLAUDE_CODE_OAUTH_TOKEN ...
station_ctl init   --- private dataset: control -------> /kaggle/input/**/station_control.json
push_kernel.sh     --- kaggle kernels push ------------> station_kernel.py
                                                           1 credentials  2 unpack  3 setup  4 GATE
                                                           5 install + probe  6 N workers
station_ctl send/deadline/stop-all                         7 control loop (every LOOP_S):
                   --- new control dataset version ---->     re-read control (UNVERIFIED), STOP files,
                                                             deadline kill, status.json, snapshots
station_ctl status <-- kaggle kernels status ----------    RUNNING / COMPLETE / ERROR  (MEASURED)
station_ctl logs   <-- kaggle kernels logs ------------    "STATION {...}" lines        (UNVERIFIED live)
station_ctl progress <- outbox dataset version --------    status.json                  (UNVERIFIED)
station_ctl output <-- kaggle kernels output ----------  8 /kaggle/working/out/: results.tar.gz, logs
```

## Evidence tags (used in every doc)

| Tag | Meaning |
|---|---|
| **MEASURED** | Measured inside a live Kaggle CPU batch session on 2026-11-22 (5 Claude Code agents on a decompilation project), or read directly from the named CLI version's help or source. Values are given. |
| **OBSERVED** | Seen by the operator while building that run (failed attempts, error messages). Not re-measured. |
| **UNVERIFIED** | Not checked by us. This includes Kaggle documentation claims. Treat it as a question. |

## Repository map

| Path | Runs on | What |
|---|---|---|
| [docs/00_runbook.md](docs/00_runbook.md) | home | step-by-step runbook with the expected output of each step |
| [docs/01_environment.md](docs/01_environment.md) | - | account, hardware, OS, packages, filesystem, network and time limits (tables) |
| [docs/02_credentials.md](docs/02_credentials.md) | - | keys dataset (default) vs Kaggle Secrets: what each one exposes |
| [docs/03_data_in_out.md](docs/03_data_in_out.md) | - | datasets in, `/kaggle/input` layout, upload speed, what leaves the session |
| [docs/04_station_kernel.md](docs/04_station_kernel.md) | - | **full annotated listing** of the kernel, plus a CONFIG reference |
| [docs/05_claude_code_headless.md](docs/05_claude_code_headless.md) | - | install, token auth, `claude -p` flags, stream-json, several instances |
| [docs/06_control_and_progress.md](docs/06_control_and_progress.md) | - | what works mid-run (measured matrix), the control-file protocol, getting progress back |
| [docs/07_correctness_gates.md](docs/07_correctness_gates.md) | - | equivalence gate before any work, kit freshness |
| [docs/08_concurrency_and_compute.md](docs/08_concurrency_and_compute.md) | - | CPU and RAM with 5 agents (measured table), sizing |
| [docs/09_shutdown_and_results.md](docs/09_shutdown_and_results.md) | - | soft stop, deadline, cap, platform limit; the results allow-list |
| [docs/10_troubleshooting.md](docs/10_troubleshooting.md) | - | exact error messages, their causes and fixes (including the failures from the measured run) |
| [docs/11_file_formats.md](docs/11_file_formats.md) | - | `kernel-metadata.json`, `dataset-metadata.json`, `station_control.json`, `status.json`, output layout |
| [docs/SECURITY.md](docs/SECURITY.md) | - | threat model and checklists |
| [docs/appendix_A_own_server_relay.md](docs/appendix_A_own_server_relay.md) | own server | optional: rsync relay through a key locked to `rrsync` |
| [scripts/station_kernel.py](scripts/station_kernel.py) | Kaggle | the station: credentials, kit, gate, N workers, control loop, results |
| [scripts/pack_kit.sh](scripts/pack_kit.sh) | home | tar + zstd, credential-path refusal, private dataset create/version |
| [scripts/make_keys_dataset.sh](scripts/make_keys_dataset.sh) | home | credentials as files in a separate private dataset |
| [scripts/push_kernel.sh](scripts/push_kernel.sh) | home | writes `kernel-metadata.json`, refuses if a run is active, `kaggle kernels push` |
| [scripts/station_ctl.sh](scripts/station_ctl.sh) | home | status, logs, output, control-file edits (send, deadline, soft-stop, stop-all), outbox |
| [scripts/load_sampler.sh](scripts/load_sampler.sh) | Kaggle | CPU/RAM sampler (TSV) |
| [scripts/stream_summary.py](scripts/stream_summary.py) | anywhere | summary of Claude Code stream-json logs; prints no message content |
| [tools/gen_kernel_listing.py](tools/gen_kernel_listing.py) | dev | regenerates docs/04 from the kernel source |
| [tests/run_tests.sh](tests/run_tests.sh) | dev | shellcheck, `bash -n`, compile, unit tests, an end-to-end kernel run, doc sync |

## Quick start

Follow [docs/00_runbook.md](docs/00_runbook.md). In short:

```bash
claude setup-token                                    # save the token to ./claude_token.txt (chmod 600)
scripts/make_keys_dataset.sh <OWNER>/<KEYS_DATASET> CLAUDE_CODE_OAUTH_TOKEN=./claude_token.txt
scripts/pack_kit.sh ~/project kit_base.tar.zst ./ds_kit --upload <OWNER>/<KIT_DATASET>
scripts/station_ctl.sh init-control <OWNER>/<CONTROL_DATASET> ./ctl
$EDITOR scripts/station_kernel.py                     # CONFIG block only
scripts/push_kernel.sh <OWNER>/<KERNEL_SLUG> <OWNER>/<KIT_DATASET> <OWNER>/<KEYS_DATASET> <OWNER>/<CONTROL_DATASET>
scripts/station_ctl.sh status <OWNER>/<KERNEL_SLUG>   # RUNNING ... COMPLETE
scripts/station_ctl.sh output <OWNER>/<KERNEL_SLUG> ./run_output
```

Expect about **5 minutes** from container start to all workers running (MEASURED, most of it the gate).

## Status of this repository

- The measured run used an earlier, project-specific version of this kernel (one CPU session, 5 Claude Code
  workers, about 1 h of work). This template generalises it and adds the lessons from that run: a changeable
  deadline and soft stop in a control file, an allow-listed results archive, credentials looked up by name, and
  process-group kills.
- **The template has been tested offline** (`tests/run_tests.sh`, including a full `main()` run with plain bash
  workers and a stub `kaggle` CLI). **It has not yet been run end to end on Kaggle.** Do a 30-minute run with one
  worker first (`RUN_HOURS = 0.5`).
- The Kaggle-native live channels (control dataset re-download, outbox dataset, live `kernels logs`) are
  **UNVERIFIED**. Without them the station still works fire-and-forget: everything comes back in the run output.

Placeholders: `<OWNER>` (your Kaggle username), `<KERNEL_SLUG>`, `<KIT_DATASET>`, `<KEYS_DATASET>`,
`<CONTROL_DATASET>`, `<OUTBOX_DATASET>`, `<RELAY_USER>`, `<RELAY_HOST>`. The repository contains no credentials,
hostnames, IPs or project data.

License: see [LICENSE](LICENSE). The owner has not chosen one yet.
