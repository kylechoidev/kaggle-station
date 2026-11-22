# 00 - Runbook: from zero to results

Each step lists the command, the expected output, and what to check. CLI output wording can differ between
`kaggle` versions. Lines marked `(wording UNVERIFIED)` show the shape of the output, not exact text.

## 0. Prerequisites

| Item | Requirement | Check |
|---|---|---|
| Kaggle account | **phone-verified**; without that, internet stays off (UNVERIFIED, per Kaggle docs) | Kaggle web: Settings, Phone verification |
| `kaggle` CLI on the home computer | 2.x; this repo was checked against **2.2.5** at home (the session image ships 2.0.2, MEASURED) | `kaggle --version` prints `Kaggle CLI 2.2.5` |
| Kaggle API credentials at home | as described in the CLI's own docs (for example `~/.kaggle/kaggle.json`, mode 600) | `kaggle kernels list --mine` lists your kernels (or prints an empty table) |
| `python3` >= 3.9, `bash`, `tar`, `zstd`, `sha256sum` | for the home scripts | `zstd --version` |
| Claude Code at home | only to run `claude setup-token` once | `claude --version` |
| A Claude subscription | every worker draws on its usage limits (docs/05) | - |
| Disk at home | about 1.3x the compressed kit size for staging | - |

Clone this repository and run the offline checks once:

```bash
bash tests/run_tests.sh
```

Expected: `ALL CHECKS PASSED`. If shellcheck is not installed you also see a `shellcheck not installed: skipped`
line. The end-to-end test reports `skipped` when no zstd decoder module is available. Both are fine.

## 1. Claude token (home)

```bash
claude setup-token            # browser login; prints a long-lived token (OBSERVED: valid for one year)
umask 077; cat > claude_token.txt    # paste the token, then Ctrl-D
```

Check: `wc -c claude_token.txt` prints a non-zero size. Never paste the token anywhere else.

## 2. Keys dataset (home)

```bash
scripts/make_keys_dataset.sh <OWNER>/<KEYS_DATASET> CLAUDE_CODE_OAUTH_TOKEN=./claude_token.txt
```

Expected:

```
staged CLAUDE_CODE_OAUTH_TOKEN (<N> bytes)
... upload progress / "Your private Dataset is being created" ...   (wording UNVERIFIED)
created private dataset <OWNER>/<KEYS_DATASET>; wait for: kaggle datasets status <OWNER>/<KEYS_DATASET>  -> ready
```

Optional extra names, added as `NAME=file` arguments:

| Name | Use |
|---|---|
| `PROJECT_API_KEY` | written to `/root/.config/project/api_key` (0600) for your workers (`FILE_CREDENTIALS`) |
| `KAGGLE_JSON` | a Kaggle API credential file the **station** uses for its own `kaggle` calls (control download, outbox). Normally **not needed**: the session's built-in login did both (MEASURED, docs/06). Add it only if those calls fail on your account. |
| `RELAY_SSH_KEY` | appendix A only |

Read docs/02 before adding anything: everyone signed in to the account can read this dataset.

## 3. Wait for the dataset to be ready (home)

```bash
kaggle datasets status <OWNER>/<KEYS_DATASET>
```

Expected: `ready` (printed without a trailing newline, so several calls in a row run together, MEASURED). Do this
after every dataset create or version, before you push. `--format json` prints
`{"status": "ready", "current_version_number": 1}` (MEASURED, CLI 2.2.5).

## 4. Kit (home)

Put everything the workers need in one directory: toolchain, project tree, gate data (docs/07). Split it into two
archives when part of it changes often. Upload the large, stable part once and reuse it; re-upload only the small
one.

```bash
scripts/pack_kit.sh ~/project/toolchain kit_base.tar.zst ./ds_kit_base --upload <OWNER>/<KIT_BASE>
scripts/pack_kit.sh ~/project/work      kit_work.tar.zst ./ds_kit_work --upload <OWNER>/<KIT_WORK>
kaggle datasets status <OWNER>/<KIT_BASE>; kaggle datasets status <OWNER>/<KIT_WORK>
```

Expected (the numbers are from the measured run's base kit):

```
packing /home/<you>/project/toolchain -> ./ds_kit_base/kit_base.tar.zst
raw 2.4G, archive 477M, <S> s
<sha256>  kit_base.tar.zst
Your private Dataset is being created. Please check progress at https://www.kaggle.com/datasets/<OWNER>/<KIT_BASE>
uploaded; wait for: kaggle datasets status <OWNER>/<KIT_BASE>  -> ready
```

| Measured run | Value |
|---|---|
| base kit | 2.4 GB raw, 499,641,599 bytes `.tar.zst` (MEASURED), `zstd -T2 -12` (OBSERVED) |
| work kit | 8.8 MB `.tar.zst` (MEASURED) |
| gate kit | 177 KB `.tar.zst` (MEASURED) |
| home uplink | about 135 KB/s, so 500 MB takes about 1 h (OBSERVED). The operator uploaded the base kit from a faster machine logged in to the same account. |

If the script prints `REFUSING: credential-looking paths`, add `EXCLUDES="pattern ..."` and run it again.

## 5. Control dataset (home)

```bash
scripts/station_ctl.sh init-control <OWNER>/<CONTROL_DATASET> ./ctl
kaggle datasets status <OWNER>/<CONTROL_DATASET>
```

Expected (MEASURED, CLI 2.2.5): `Your private Dataset is being created. Please check progress at ...`, then
`control dataset <OWNER>/<CONTROL_DATASET> ready in ./ctl; ...`, then `ready`. `./ctl/station_control.json`
starts at `seq` 1 with no orders. Format: docs/11.

Optional, for progress without your own server (MEASURED to work with the session login, docs/06):

```bash
scripts/station_ctl.sh init-outbox <OWNER>/<OUTBOX_DATASET> ./outbox
```

## 6. Configure the kernel (home)

Edit only the CONFIG block of `scripts/station_kernel.py` (reference: docs/04). The minimum:

| Setting | First run | Later |
|---|---|---|
| `RUN_HOURS` | `0.5` | your plan; the control file can move it |
| `MAX_HOURS` | `1` | below the platform limit minus about 15 min |
| `KIT_ARCHIVES` | your archive file names | |
| `SETUP_SHELL`, `REMOVE_AFTER_UNPACK`, `PATH_LINKS` | what your toolchain needs | |
| `GATE_*` | your gate (docs/07), or `GATE_CMD = None` for a first smoke test | |
| `WORKERS` | one worker | about 4 heavy workers per session (docs/08) |
| `BRIEF_TEMPLATE`, `WORKER_CMD` | your brief and model | |
| `CONTROL_DATASET` | `'<OWNER>/<CONTROL_DATASET>'` | |
| `OUTBOX_DATASET` | `None` or `'<OWNER>/<OUTBOX_DATASET>'` | |
| `RESULT_GLOBS`, `RESULT_SUFFIXES` | where your workers write results | |

Then run `bash tests/run_tests.sh` again. It compiles the edited kernel.

## 7. Push (home): this starts the run

```bash
DRY_RUN=1 scripts/push_kernel.sh <OWNER>/<KERNEL_SLUG> <OWNER>/<KIT_BASE> <OWNER>/<KIT_WORK> \
          <OWNER>/<KEYS_DATASET> <OWNER>/<CONTROL_DATASET>          # prints kernel-metadata.json only
scripts/push_kernel.sh <OWNER>/<KERNEL_SLUG> <OWNER>/<KIT_BASE> <OWNER>/<KIT_WORK> \
          <OWNER>/<KEYS_DATASET> <OWNER>/<CONTROL_DATASET>
```

Expected: the metadata JSON, then `Kernel version 1 successfully pushed.  Please check progress at
https://www.kaggle.com/code/<OWNER>/<KERNEL_SLUG>` (MEASURED, CLI 2.2.5), then the `status:` and `output:` hints. The script refuses if `kaggle kernels status`
reports a running or queued run (`refusing: <OWNER>/<KERNEL_SLUG> has status "KernelWorkerStatus.RUNNING" ...`,
MEASURED). `FORCE=1` overrides it, but a push while a run is going does **not** stop it: both versions run at once, each in its own session, and `kaggle kernels status` then reports only the newest version (MEASURED). Version N's logs and output stay readable as
`<OWNER>/<KERNEL_SLUG>/<N>`.

Slug rules (MEASURED, CLI 2.2.5 source): the title must be at least 5 characters, and the slug should equal the
slugified title. The script uses the slug as the title.

## 8. Watch (home)

```bash
scripts/station_ctl.sh status <OWNER>/<KERNEL_SLUG>
```

| Output contains | Meaning |
|---|---|
| `QUEUED` | waiting for a machine (UNVERIFIED wording; not seen: a CPU push showed `RUNNING` within 10 s, MEASURED) |
| `RUNNING` | the run is going (MEASURED: `KernelWorkerStatus.RUNNING`) |
| `COMPLETE` | finished; output can be downloaded (MEASURED: `KernelWorkerStatus.COMPLETE`, output available at once) |
| `ERROR` | the kernel exited non-zero, for example gate or probe failed; read `out/setup.log` in the output |
| `CANCEL` | cancelled in the web UI (the CLI has no cancel command, MEASURED for 2.0.2 and 2.2.5) |

Poll every few minutes. While the run is going, `kaggle kernels output` and `kaggle kernels files` return nothing
(MEASURED, CLI 2.0.2 and 2.2.5). For live lines use step 10.

Measured timeline from container start (docs/04 has the full table): kit unpacked at +25 s, gate finished at
+3 min 27 s, probe OK at +3 min 50 s, all 5 workers started by +5 min 10 s.

## 9. Steer (home, optional)

```bash
scripts/station_ctl.sh send      ./ctl W1 "After this batch switch to slice 3. Replaces message m2."
scripts/station_ctl.sh send      ./ctl '*' "Close every claim before 18:30 UTC."
scripts/station_ctl.sh deadline  ./ctl 2026-01-01T19:00:00Z
scripts/station_ctl.sh soft-stop ./ctl 2026-01-01T18:30:00Z
scripts/station_ctl.sh stop-all  ./ctl on
```

Each command bumps `seq` and publishes a new control dataset version. The kernel picks it up at its next poll
(`CONTROL_POLL_S`, default 300 s). MEASURED with `CONTROL_POLL_S = 120`: applied 36 s after `station_ctl.sh` returned
(`control: deadline ...`, `control: message m2 -> S1` in the log). A worker reads its INBOX at its next batch
boundary, which takes minutes.

## 10. Progress (home, optional)

```bash
scripts/station_ctl.sh logs     <OWNER>/<KERNEL_SLUG> -f          # = kaggle kernels logs -f (CLI 2.2.5): live lines
scripts/station_ctl.sh progress <OWNER>/<OUTBOX_DATASET> ./outbox # if OUTBOX_DATASET is set
```

MEASURED (2026-11-22, CLI 2.2.5 at home): `logs -f` streams `setup.log` lines and `STATION {...}` lines within seconds
and exits when the run ends. `progress` prints `Dataset URL: ...` and `License(s): other`, then the latest
`status.json`. Without `-f`, `kaggle kernels logs` prints nothing during the run (CLI 2.0.2 and 2.2.5) and the whole
log as a JSON array after the end.

## 11. Collect (home, after COMPLETE or ERROR)

```bash
scripts/station_ctl.sh output <OWNER>/<KERNEL_SLUG> ./run_output
ls ./run_output/out
mkdir review && python3 -I -c 'import tarfile,sys; tarfile.open(sys.argv[1]).extractall(sys.argv[2], filter="data")' \
    ./run_output/out/results.tar.gz review
python3 -I scripts/stream_summary.py ./run_output/out/logs/*.log
```

Expected (MEASURED): `./run_output/<KERNEL_SLUG>.log` (the kernel's stdout) and in `out/`: `setup.log`,
`status.json` (with `"final": true` if the kernel reached the end), `gate_station.json` (only with a gate),
`logs/<WORKER>.log`, `results.tar.gz`. Layout: docs/11. The output of an earlier version stays downloadable with
`kaggle kernels output <OWNER>/<KERNEL_SLUG>/<N> -p <DIR> -o` (MEASURED).

`filter="data"` needs Python 3.12+ (or a security-patched 3.8 to 3.11). Treat everything as untrusted (docs/SECURITY.md). Verify results with your authoritative check before you use them.

## 12. Clean up (home)

| What | Command |
|---|---|
| keys dataset, at the end of a campaign or after anything suspicious | `kaggle datasets delete <OWNER>/<KEYS_DATASET> -y` |
| Claude token | revoke it in your Claude account settings (exact menu UNVERIFIED); create a new one for the next campaign |
| control and outbox datasets | `kaggle datasets delete <OWNER>/<CONTROL_DATASET> -y` (or keep them and reset with `init-control` in a fresh dir) |
| a test kernel | `kaggle kernels delete <OWNER>/<KERNEL_SLUG> -y` (deletes its versions and outputs) |
| kit datasets you no longer need | `kaggle datasets delete <OWNER>/<KIT_...> -y` |

Before the next run: `scripts/station_ctl.sh reset ./ctl`. An old `stop_all: true` would stop the new workers at
once, and a new run delivers every message still in the file (the kernel remembers delivered ids only within
one run).
