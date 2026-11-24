# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are dates until the owner picks a scheme.

## [Unreleased] - 2026-11-24 (free-model swarm)

### Added
- docs/12_free_model_swarm.md: many workers on free hosted LLMs across Kaggle CPU sessions, an ARM VM, a VPS hub and
  a laptop. Quickstart with expected output; the provider slot, probe-and-rank and the deal hunt at every start; the
  worker loop and adapters; an always-on hub with no model (singletons with one assigned host, a watchdog with
  restartable vs never-restart stop reasons, a results ledger, per-host verifier self-update with recheck and
  rollback, a status page); Kaggle multi-slot scaling (5 CPU sessions per account, phone verification needed for
  internet, relay, stale-slot watchdog, pause vs yield); a trigger-only coordinator with request files and handback
  by heartbeat; dated pitfalls.
- swarm/: `worker.py` (pluggable adapters), `adapters/pytests_example.py` (runnable example: functions that pass unit
  tests), `adapters/decomp_pool_skeleton.py` (byte-matching decompilation pool, TODOs), `probe_providers.py`,
  `yield_test.py`, `providers.example.json`, `hub/` (tick, host, guard, push_host, self_update, config example),
  `kaggle/` (multi-slot scheduler, kernel wrapper, code bundler, config example), `coord/` (patrol loop, triggers,
  brief template). All paths from `SWARM_ROOT` and one config file.
- tests/test_swarm.py: offline end-to-end tests with a stub OpenAI-compatible server.

### Tested
- MEASURED 2026-11-24: the worker with the example adapter from a clean clone against a real free provider; the
  offline suite. Not re-tested in this generic copy: the hub over ssh between real hosts, the Kaggle scheduler and
  kernel on real accounts, the coordinator with a real model call (they ran in the source deployment).

## [Unreleased] - 2026-11-22 (live test)

### Verified on Kaggle
- First end-to-end run of the template from a fresh clone, following docs/00 step by step: a 4 KB kit packed with
  `pack_kit.sh`, an existing keys dataset, a control and an outbox dataset made with `station_ctl.sh`, one shell
  worker and one Claude Code worker (preset flags), `RUN_HOURS = 0.5`, CPU, no gate.
- MEASURED answers to the questions marked UNVERIFIED before: `kaggle kernels logs -f` streams live (plain `logs`
  stays empty until the end); the session's built-in login downloads newer control dataset versions and publishes
  outbox versions (no `KAGGLE_JSON`); the run output is downloadable as soon as status is `COMPLETE`, and each
  version's output stays downloadable as `<OWNER>/<KERNEL_SLUG>/<N>`; a `FORCE=1` re-push starts a parallel run and
  does not stop the running one, while `kernels status` reports only the newest version.
- Deadline moved earlier through the control file, soft stop, SIGTERM at the deadline, results packed, final
  `status.json` with `"final": true`: all as documented.

### Fixed
- `station_ctl.sh logs` takes `-f` (live); without it the CLI prints nothing during a run.
- docs/00: real CLI output for steps 3 to 11 (dataset create line, `ready` without newline, push line, `COMPLETE`,
  `progress` header lines, `<KERNEL_SLUG>.log` in the output), `kaggle kernels delete` in the clean-up table,
  `KAGGLE_JSON` marked as normally not needed.
- docs/03: the kernel does not log or check the kit's sha256 (the old text said it did).
- docs/05: how to run mixed workers (shell and Claude Code) with one `WORKER_CMD`, and why to pass `{BRIEF_FILE}`
  rather than `{BRIEF}` inside `bash -c`.
- docs/SECURITY, docs/02: the session login has write access to the owner's datasets (MEASURED), not only read.
- docs/01, 04, 06, 09, 10, 11, README, kernel comments, `push_kernel.sh` help: UNVERIFIED rows replaced by measured values.

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
- (Closed by the live test above.) The template had not yet been run end to end on Kaggle, and the Kaggle-native
  live channels were UNVERIFIED.
