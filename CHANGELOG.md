# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are dates until the owner picks a scheme.

## [Unreleased] - 2026-11-22

### Added
- `scripts/station_kernel.py`: generic station kernel. Credentials looked up by name (keys dataset file, then
  Kaggle Secret); kit unpack from `.tar.zst` with Python `zstandard` or `compression.zstd`; setup shell and
  environment probe; equivalence gate that fails closed; any worker command (Claude Code preset) for N workers in
  their own process groups; control loop with a control file (`seq`, deadline capped by `MAX_HOURS`, soft stop,
  `stop_all`, messages delivered once by id); `status.json`, `STATION` stdout lines, optional outbox dataset and
  optional own-server relay; allow-listed `results.tar.gz` that skips unchanged kit files, symlinks and large
  files, with snapshots every 30 min.
- Home scripts: `pack_kit.sh`, `make_keys_dataset.sh`, `push_kernel.sh` (refuses if a run is active),
  `station_ctl.sh` (status, logs, output, control edits, outbox), `load_sampler.sh`, `stream_summary.py`.
- Docs 00 to 11, SECURITY, appendix A. Every fact is tagged MEASURED, OBSERVED or UNVERIFIED.
- `tests/`: shellcheck, `bash -n`, compile checks, unit tests, an end-to-end `main()` run with a stub `kaggle`
  CLI, and a docs/04 sync check. `tools/gen_kernel_listing.py` regenerates the annotated listing.

### Changed (relative to the kernel used in the measured run)
- The deadline and soft stop moved from compiled-in constants to the control file. The per-worker `timeout` is
  now only a generous cap.
- Credentials as files in a private dataset are the default; Kaggle Secrets are supported for editor-started runs.
- The rented-server relay is optional (appendix A). The main path needs only a home computer and Kaggle.

### Known gaps
- The template has not yet been run end to end on Kaggle. The Kaggle-native live channels (control dataset
  re-download, outbox dataset, live `kernels logs -f`) are UNVERIFIED.
