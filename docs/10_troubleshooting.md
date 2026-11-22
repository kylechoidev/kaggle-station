# 10 - Troubleshooting

## Failures from the measured run

Each of these cost one attempt of about 4 minutes (push, wait, read the log). All are fixed in the template.

| # | Symptom (exact text where known) | Cause | Fix | Tag |
|---|---|---|---|---|
| 1 | `UserSecretsClient().get_secret()` fails: `HTTP 400 Bad Request`, then `ConnectionError: Connection error trying to communicate with service` | Kaggle Secrets are only available to runs started from the web editor; the version was pushed with the CLI | credentials as files in a private keys dataset (docs/02) | OBSERVED |
| 2 | editor "Save Version" fails: `ConcurrencyViolation Sequence number must match Draft record` | a CLI push created a version while the editor had the notebook open | reload the editor before saving; better, do not mix the editor and CLI pushes | OBSERVED |
| 3 | setup step `source env.sh` returns rc 127 (`source: not found`) | `subprocess.run(..., shell=True)` uses `/bin/sh`; `source` is a bash builtin | `executable='/bin/bash'` (the kernel's `sh()` does this) | OBSERVED |
| 4 | checker fails `ModuleNotFoundError` for a module that was just installed | the kit's environment script put a **copied virtualenv** first on `PATH`; its `python3` shadowed the system `python3` that pip installed into | delete the venv after unpacking (`REMOVE_AFTER_UNPACK`), install with `python3 -m pip install ... --break-system-packages` in `SETUP_SHELL`; diagnose with `ENV_PROBE` (`command -v python3` plus an import probe) **after** sourcing the environment | OBSERVED |
| 5 | Wine fails on a prefix copied from another machine | prefix owned by another uid; the session runs as root | `chown -R "$(id -u):$(id -g)" <prefix>` in `SETUP_SHELL` | OBSERVED |
| 6 | a 500 MB upload from home takes over an hour | home uplink about 135 KB/s | upload big archives once and reuse them; version only the small archive; or upload from a faster machine logged in to the same account | OBSERVED |
| 7 | the stop time could not be moved after launch | stop time and `timeout` compiled into the kernel | control file (`deadline_utc`, `soft_stop_utc`), generous `MAX_HOURS` (docs/09) | OBSERVED |
| - | `Error in sitecustomize ... No module named 'wrapt'` on every Python start | image noise | harmless; `pip install wrapt` silences it | OBSERVED |

## By symptom

| `setup.log` / status shows | Likely cause | Fix |
|---|---|---|
| `missing credential <NAME> - a file of that name ...` | keys dataset not in `dataset_sources`; file not named exactly `<NAME>`; dataset not `ready` | check `kernel-metadata.json` (`DRY_RUN=1 push_kernel.sh`), `kaggle datasets files <OWNER>/<KEYS_DATASET>`, `kaggle datasets status` |
| `missing input <archive> under /kaggle/input` | kit dataset not attached, still processing, or renamed | same checks; inputs are found by **file name** |
| `FAILED rc <n> set -e ...` (setup shell) | a `SETUP_SHELL` command failed; stdout and stderr tails follow | fix the command; test it locally in a clean Ubuntu 24.04 container |
| `env probe: ...` shows an unexpected python3 | venv on `PATH` (#4) | `REMOVE_AFTER_UNPACK` |
| `gate compared N differences D [...]` with D > 0 | toolchain or environment differs from the reference | diff `out/gate_station.json` against the reference; usual suspects are #4, missing modules under `python3 -I`, absolute paths (`PATH_LINKS`), locale or timezone |
| `gate unreadable: ...` | checker crashed or wrote nothing | run `GATE_CMD` in an interactive Kaggle notebook with the same datasets attached |
| `TIMEOUT <cmd>` | `GATE_TIMEOUT_S` or install/probe timeout hit | raise the timeout; check internet |
| `curl: (6) Could not resolve host` during install | internet off: account not phone-verified, or `enable_internet` false | verify the phone number; `"enable_internet": true` |
| `PROBE FAILED (token? internet? usage limit?)` | token wrong, expired or revoked; no internet; usage window spent | `claude setup-token` again and rebuild the keys dataset; check `rate_limit_event` in earlier logs |
| workers exit within a minute, rc 0 | a STOP file or other stop marker was packed into the kit, or `stop_all: true` was left in the control file | do not pack `agents/*/STOP`; `station_ctl.sh reset` |
| new run receives old messages | the control file still holds them; ids are remembered within one run only | `station_ctl.sh reset ./ctl` before pushing |
| `control download failed rc 1 ...` | the session cannot download the control dataset with its built-in auth (UNVERIFIED path) | add `KAGGLE_JSON` to the keys dataset, or use level 0 (docs/06) |
| `outbox version rc 1 ...` | the same for writing | same |
| `bad control document ...` | invalid JSON or time format | `station_ctl.sh show ./ctl`; edit only with `station_ctl.sh` |
| message never acted on | worker has not reached a batch boundary; ambiguous text | wait; say what it replaces; use absolute UTC times |
| worker rc 124 | the `MAX_HOURS` cap | expected only if the deadline was at the cap |
| load far above 4, everything slow | workers run parallel builds | brief: one heavy process per worker, `--jobs 1` (docs/08) |
| `OSError: [Errno 28] No space left on device` | `/kaggle/working` is 20 GB | keep the kit and scratch outside `/kaggle/working`; trim logs |
| process killed, no traceback | out of memory (30 GiB cgroup, no swap) | fewer parallel heavy jobs |
| `status.json` has no `"final": true` | container killed before the end (platform limit, cancel) | lower `MAX_HOURS`; use the last `results.tar.gz` snapshot |
| `push_kernel.sh`: `refusing: ... RUNNING` | a run of this kernel is still going | wait, or `FORCE=1` (effect on the running version UNVERIFIED) |
| CLI: `Title must be at least five characters` | slug shorter than 5 characters | longer slug |
| CLI: `Your kernel title does not resolve to the specified id` | title and slug differ | `push_kernel.sh` uses the slug as title |
| `kaggle` warns that it is outdated, inside the session | the image ships 2.0.2 | harmless |
| home: `REFUSING: credential-looking paths` from `pack_kit.sh` | a path matched the credential pattern | `EXCLUDES="pattern ..."`, or rename an innocent file |

## Diagnose locally first

Most failures are setup failures that cost a 4-minute round trip each. Reproduce `SETUP_SHELL`, `ENV_PROBE` and
`GATE_CMD` in a local `ubuntu:24.04` container running as root with the kit unpacked at `WORKDIR`. Then push.
