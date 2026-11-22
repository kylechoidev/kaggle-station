# 03 - Data in and out

## In: private datasets

| Step | Command (home) | Notes |
|---|---|---|
| create | `kaggle datasets create -p <DIR> -q` | `<DIR>` holds the files and `dataset-metadata.json` (docs/11). Private unless `-u/--public`. |
| new version | `kaggle datasets version -p <DIR> -m "<note>" -q` | `-d` deletes old versions; `-r zip\|tar\|skip` sets how sub-directories are uploaded |
| wait | `kaggle datasets status <OWNER>/<SLUG>` | prints `ready`; `--format json` adds `current_version_number` |
| list files | `kaggle datasets files <OWNER>/<SLUG>` | |
| delete | `kaggle datasets delete <OWNER>/<SLUG> -y` | |
| attach to the run | `"dataset_sources": ["<OWNER>/<SLUG>", ...]` in `kernel-metadata.json` | `scripts/push_kernel.sh` writes it |

Flags MEASURED from CLI 2.2.5 help. A run mounts the version that is current when it starts (UNVERIFIED, but the
gate in docs/07 and the logged sha256 catch a stale kit). Wait for `ready` before pushing.

### Recommended dataset split

| Dataset | Content | Changes | Measured size |
|---|---|---|---|
| kit base | toolchain (compiler, Wine, checker, target image) | rarely: upload once, reuse | 2.4 GB raw, 500 MB `.tar.zst` |
| kit work | project tree, scripts, knowledge, state | every run: new version | 8.8 MB |
| gate | sample list and reference verdicts (docs/07) | when the toolchain changes | 177 KB |
| keys | credentials (docs/02) | on rotation: delete and create again | bytes |
| control | `station_control.json` (docs/06) | while running | bytes |
| outbox (optional) | `status.json` written by the station | while running | bytes |

### Where datasets appear in the session

MEASURED: two layouts in **one** session.

```
/kaggle/input/datasets/<owner>/<slug>/<files>      # the kit datasets in the measured run
/kaggle/input/<slug>/<files>                       # another dataset in the same run
```

So never hard-code a path. The kernel finds inputs by file name:

```python
glob.glob('/kaggle/input/**/' + name, recursive=True)
```

That is why archive and credential file names must be unique across all attached datasets.

### Packing

`scripts/pack_kit.sh` runs `tar -C <parent> --exclude=... -cf - <dir> | zstd -q -12 -T0`, writes a `.sha256`, refuses
credential-looking paths, then creates or versions the dataset.

| Measured fact | Value | Tag |
|---|---|---|
| Compression | 2.4 GB raw to 499,641,599 bytes (about 4.8:1), `zstd -T2 -12` | MEASURED size / level OBSERVED |
| Unpack in the session, 500 MB archive (Python `zstandard` stream into `tarfile`) | **14 s** | MEASURED |
| Unpack, 8.8 MB archive with many small files | 11 s | MEASURED |
| `zstd` CLI in the image | absent; the kernel uses the `zstandard` module (or `compression.zstd` on Python 3.14+) | MEASURED |
| Home uplink of the measured operator | about 135 KB/s, so 500 MB took over an hour; uploading from a faster machine logged in to the same account took minutes | OBSERVED |

Rules from the measured run:

| Rule | Reason |
|---|---|
| Upload big, stable archives once and reuse them; version only the small one | slow home uplinks (OBSERVED) |
| Do not pack virtualenvs; install Python packages in `SETUP_SHELL` for the session's `python3` | a copied venv put first on `PATH` shadowed the system python3, and the checker could not import its module (OBSERVED) |
| Recreate the reference machine's absolute paths with `PATH_LINKS` symlinks instead of repacking | worked in the measured run (MEASURED) |
| `chown -R` Wine prefixes to the session user (root) in `SETUP_SHELL` | a prefix owned by another uid fails (OBSERVED) |
| Put the kit's commit or sha256 inside the kit and log it | tells you later which kit produced a result |

### What must not be uploaded unless the data owner decides

A private dataset is still data stored by a third party under its terms.

| Category | Examples | Decision |
|---|---|---|
| Third-party proprietary inputs | original binaries, their disassembly, extracted assets | the data owner, not the station operator; this repo ships none |
| Credentials inside the kit | SSH keys, API keys, `.env`, cloud configs | never: use the keys dataset. `pack_kit.sh` refuses obvious paths (a net, not a guarantee) |
| Personal data, NDA material, other people's work | - | no |

## Out: what leaves the session

| Route | What | When | Tag |
|---|---|---|---|
| Run output | everything under `/kaggle/working` (the kernel uses `/kaggle/working/out/`) | after the run ends: `kaggle kernels output <OWNER>/<KERNEL_SLUG> -p <DIR> -o` | MEASURED: empty while running / after the end: UNVERIFIED (per Kaggle docs) |
| stdout | `STATION {...}` progress lines, log lines | `kaggle kernels logs` | UNVERIFIED live (docs/06) |
| Outbox dataset | `status.json` | every `OUTBOX_EVERY_S` | UNVERIFIED (docs/06) |
| Own server | `status.json` | appendix A | MEASURED design (relay worked in the measured run) |

### The results allow-list

`results.tar.gz` contains a file only if **all** of these hold (`select_results()` in the kernel):

| Condition | Default |
|---|---|
| matches a `RESULT_GLOBS` pattern relative to `WORKDIR` | `agents/*/*`, `src/**/*` |
| ends with one of `RESULT_SUFFIXES` | `.txt .md .tsv .json .jsonl .c .cpp .h .hpp .py .sh` |
| matches no `RESULT_EXCLUDE_GLOBS` pattern (relative path or basename) | `*/STOP`, `*/BRIEF.md`, `*.key`, `*.pem`, `*token*`, `*secret*`, `*api_key*` |
| is a regular file, not a symlink | - |
| size <= `RESULT_MAX_FILE_BYTES` | 2,000,000 |
| is new or changed since the kit was unpacked (`RESULT_ONLY_NEW_OR_CHANGED`) | `True`: compares size and mtime with a manifest taken after setup |

So toolchain and target data from the kit never come back unless a worker rewrote them. The archive is written to
`results.tar.gz.part` and renamed, so a kill during packing never leaves a truncated archive.

Worker logs (`out/logs/<NAME>.log`) contain everything the agent read with its tools, which can include private
inputs. They are in the run output, which stays private to your account. Do not publish them.
