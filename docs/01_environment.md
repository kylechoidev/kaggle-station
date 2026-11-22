# 01 - Environment: account, machine, software, limits

All MEASURED values come from one CPU batch session (script kernel pushed with the CLI, internet on, no
accelerator) on 2026-11-22. Kaggle changes its image and limits, so check the values in your first run.
`scripts/load_sampler.sh` and the commands in the last column help with that.

## Account

| Fact | Value | Tag | How to check |
|---|---|---|---|
| Internet needs a phone-verified account | without it, `enable_internet: true` has no effect | UNVERIFIED (per Kaggle docs; OBSERVED: of several accounts, only the phone-verified ones had internet) | `curl -sI https://pypi.org` in the run |
| Kernels and datasets created by the CLI are private by default | `is_private` default `true`; `datasets create` is private unless `-u/--public` | MEASURED (CLI 2.2.5 source and help) | `kaggle datasets create -h` |
| `enable_internet` default when missing | `true` | MEASURED (CLI 2.2.5 source: `get_bool(meta_data, "enable_internet", True)`) | - |
| Concurrent sessions per account | a cap exists; "5 concurrent CPU sessions" was reported by a peer project | UNVERIFIED | `kaggle kernels list --mine` |
| Sessions vs processes | one session ran 5 Claude Code processes plus their tools | MEASURED | - |
| Weekly GPU/TPU quota | exists, about 30 h/week GPU has been quoted; not needed for a station | UNVERIFIED | Kaggle web: Settings |
| Terms of use | read them yourself; long-running autonomous agents are not explicitly addressed | UNVERIFIED | - |

## Hardware (CPU session)

| Resource | Value | Tag | Command |
|---|---|---|---|
| vCPUs | 4 = 1 socket x 2 cores x 2 threads, Intel Xeon @ 2.20 GHz, KVM | MEASURED | `nproc; lscpu` |
| CPU quota | cgroup `cpu.max` = `400000 100000` (4.0 CPUs) | MEASURED | `cat /sys/fs/cgroup/cpu.max` |
| RAM | `free`: 31 GiB; cgroup `memory.max`: 30 GiB | MEASURED | `cat /sys/fs/cgroup/memory.max` |
| Swap | none | MEASURED | `free -h` |
| GPU | none (CPU session) | MEASURED | - |
| Region | a GCP zone in env `KAGGLE_GCP_ZONE` (an Asia zone in this run; you cannot choose it) | MEASURED | `echo $KAGGLE_GCP_ZONE` |

## Filesystem

| Path | Size / type | Lifetime | Tag |
|---|---|---|---|
| `/kaggle/input` | read-only mounts of attached datasets; sub-path varies (docs/03) | the run | MEASURED |
| `/kaggle/working` | 20 GB loop device | **saved as the run output** when the run ends | MEASURED size / saving: UNVERIFIED (per Kaggle docs) |
| `/` (overlay) | shows an 8 TB shared host filesystem; real per-session quota not visible | discarded | MEASURED / quota UNVERIFIED |
| `/dev/shm` | 14 GB | discarded | MEASURED |
| `/root`, `/home`, `/tmp` | on `/` | discarded | MEASURED (not in the output) |
| Kit unpacked in the session | 3.0 GB tree after the workers started writing | discarded | MEASURED |

Keep the kit and scratch files outside `/kaggle/working`. Only results belong there.

## Operating system and software

| Item | Value | Tag |
|---|---|---|
| OS | Ubuntu 24.04.5 LTS, x86_64 | MEASURED |
| Kernel | 6.18.x | MEASURED |
| User | `root`, `sudo` available | MEASURED |
| Python | 3.13 at `/usr/bin/python3` | MEASURED |
| pip | 26.x | MEASURED |
| `pip install` into the system python3 | worked; the measured run also used `--break-system-packages` as a fallback | MEASURED / flag need UNVERIFIED |
| `apt-get update && apt-get install` | works (internet on) | MEASURED |
| Present | `rsync` 3.2.7, `rrsync`, `ssh`, `git`, `curl`, `pigz` | MEASURED |
| Absent | `zstd` CLI, `docker` | MEASURED |
| Python modules preinstalled | `zstandard`, `kaggle_secrets`, `kagglehub` | MEASURED |
| `kaggle` CLI in the image | 2.0.2 | MEASURED |
| Startup noise | `Error in sitecustomize ... No module named 'wrapt'` on Python start; harmless | OBSERVED |
| Wine | a portable Wine build from the kit ran a Windows compiler as root, after `chown` of the prefix | MEASURED (worked) / chown: OBSERVED |
| Claude Code | 2.1.330 by the native installer, about 364 MB, no Node.js needed | MEASURED |

## Process limits

| Limit | Value | Tag |
|---|---|---|
| cgroup `pids.max` | 38508 | MEASURED |
| `ulimit -n` | 1048576 | MEASURED |
| `ulimit -u` | unlimited | MEASURED |

## Network

| Direction | Result | Tag |
|---|---|---|
| Outbound HTTPS to pypi.org, github.com, claude.ai, api.anthropic.com, archive.ubuntu.com | works | MEASURED |
| Outbound TCP/22 (ssh, rsync over ssh) | works | MEASURED |
| Inbound connections to the session | none possible (no public address, no exec into a batch run) | MEASURED (no such facility in the CLI or the batch session) |

## Environment variables (names only)

| Variable | Value / meaning | Tag |
|---|---|---|
| `KAGGLE_KERNEL_RUN_TYPE` | `Batch` for a CLI-pushed script | MEASURED |
| `KAGGLE_USER_SECRETS_TOKEN`, `KAGGLE_DATA_PROXY_TOKEN`, `KAGGLE_API_V1_TOKEN` | Kaggle session tokens, present in every process | MEASURED |
| `KAGGLE_GCP_ZONE` | the session's zone | MEASURED |

Inside the session, the preinstalled `kaggle` CLI is **authenticated as the account owner** without any
`kaggle.json`: `kaggle kernels list --mine` worked (MEASURED, read only; write is UNVERIFIED). Security
consequences: docs/SECURITY.md.

## Time limits

| Fact | Value | Tag |
|---|---|---|
| Max wall clock per session | 12 h CPU/GPU, 9 h TPU | UNVERIFIED (per Kaggle docs; has changed before) |
| `kaggle kernels push -t SECONDS` | per-run limit; help: "The global maximum time will not be exceeded." | MEASURED (CLI 2.2.5 help) |
| Batch runs need no open browser | a pushed run kept going with no editor open | MEASURED |
| Interactive editor idle timeout | about 20 min has been quoted | UNVERIFIED |
| Longest run measured here | about 1 h of work | MEASURED (the 12 h ceiling was not tested) |

Template defaults: `RUN_HOURS = 3`, `MAX_HOURS = 11`. Keep `MAX_HOURS` below the platform limit minus about
15 minutes for setup (about 5 min, MEASURED) and packing.

## Mid-run facilities (detail in docs/06)

| Facility | Result during a running batch run | Tag |
|---|---|---|
| `kaggle kernels status` | `KernelWorkerStatus.RUNNING` | MEASURED |
| `kaggle kernels logs` (CLI 2.0.2) | nothing | MEASURED |
| `kaggle kernels logs -f` (CLI 2.2.5, "Stream live execution logs") | not tried | UNVERIFIED |
| `kaggle kernels files` / `output` | nothing until the run ends | MEASURED |
| Attach a new dataset at run time (`kagglehub.dataset_download`) | `New Datasets cannot be attached in non-interactive sessions` | MEASURED |
| Cancel from the CLI | no such subcommand (2.0.2: `list, files, get, init, push, pull, output, status, logs, update, delete`; 2.2.5 adds `topics`) | MEASURED |
