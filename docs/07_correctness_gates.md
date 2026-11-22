# 07 - Correctness gates: prove the station is equivalent before it works

A station is a *different machine* running your toolchain: different CPU, kernel, libc, Python, Wine, locale,
paths. If its verdicts differ from your reference machine's, every result it produces is suspect, and in a
decompilation project a wrong "matches" verdict is worse than no result. So: **gate first, work second**.

## Configuration

| Setting | Default | Meaning |
|---|---|---|
| `GATE_CMD` | `python3 -I tools/gate_check.py gate/sample.txt > gate/station.json` | runs in `WORKDIR` with `/bin/bash`; `None` skips the gate |
| `GATE_REFERENCE` | `gate/reference.json` | verdicts from the reference machine |
| `GATE_OUTPUT` | `gate/station.json` | verdicts written by `GATE_CMD` |
| `GATE_FIELD` | `status` | per-item field compared |
| `GATE_TIMEOUT_S` | 1800 | a hung checker fails the gate |

File format (both files):

```json
{"<item id>": {"status": "match"}, "<item id>": {"status": "no match"}}
```

The kernel fails the gate (exit 1, no workers) when any reference item's `GATE_FIELD` differs or is missing in the
output, when the reference is empty, or when either file cannot be read. `setup.log` shows
`gate compared <N> differences <D> [first five ids]`, and `out/gate_station.json` keeps the station's verdicts.

## The equivalence gate (MEASURED design)

1. On the reference machine pick a fixed sample of work items covering the variety you care about (the measured
   run used **156 functions** across sizes and kinds, including known *non*-matches).
2. Run your checker there; save per-item verdicts as JSON: `{"<item>": {"status": "match"}, ...}`.
3. Ship the sample list + reference verdicts as a small dataset (177 KB here).
4. In the station, run the same checker on the same sample **before** starting any worker, and compare the
   verdict field item by item.
5. **Any** difference, a missing item, an empty reference, or a parse error -> log it and `exit(1)`.
   No workers start. (A gate that can't be evaluated is a failed gate.)

Measured result: `checked 156 {'match': 151, 'no match': 5}`, `status differences 0`, in 170 s with 2 parallel jobs.
Including known non-matches matters: a broken checker that says "match" to everything would fail the gate.

The station also copies its verdict file into the run output so you can diff it later.

## Kit freshness

The gate proves the toolchain behaves the same; it does not prove the *work state* is current. Things that went
stale or could go stale between packing and running:

- **Project state** (which items are already done by others, lock lists, naming registries): pack it last, right
  before pushing, and have workers re-query live state before acting (the measured workers re-checked
  "openness" of items right before screening because other teams sweep the same lists within minutes).
- **A kill switch**: the measured brief told workers to stop if a `KIT_STALE` file appears. With the template,
  use `station_ctl.sh stop-all ./ctl on` or a message (06) when the reference changes underneath the station.
- **Version stamp**: write the kit's git commit / sha256 into the archive and print it from `ENV_PROBE`, so it
  lands in `setup.log`. When you look at results later you know which kit produced them.
- **Dataset version**: a run mounts the dataset version current at start. Wait for `kaggle datasets status`
  = ready after uploading (03).

## Environment pitfalls the gate caught or would catch

- A Python venv packed from the reference machine shadowed the session's `python3` through `PATH`
  (deleted at setup in the measured run). A gate with a Python-based checker fails loudly on this.
- Missing Python modules under `python3 -I` (isolated mode ignores user site-packages): install with the same
  interpreter the tools use; the measured setup logs `<module> for python3 -I: <version>` as a check.
- Absolute paths baked into toolchain configs: symlink the reference paths to the unpack location.

## Results are untrusted until re-verified

The gate reduces risk; it doesn't remove it. Anything a station produces that will be published or submitted
should be verified by the authoritative system (in the measured project, the project's own server-side check
decides; the station never self-certifies). See SECURITY.md, "untrusted outputs".
