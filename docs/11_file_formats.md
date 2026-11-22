# 11 - File formats

## `kernel-metadata.json` (written by `scripts/push_kernel.sh`)

Fields, types, defaults and validation as implemented in **kaggle CLI 2.2.5** `kernels push` (MEASURED from source).

| Field | Type | Allowed / rule | CLI default if missing | Station value |
|---|---|---|---|---|
| `id` | string | `<owner>/<slug>`; must not contain a version | - (`id` or `id_no` required) | `<OWNER>/<KERNEL_SLUG>` |
| `id_no` | int | numeric kernel id, an alternative to `id` | - | not used |
| `title` | string | at least 5 characters; should slugify to the slug, otherwise the CLI warns `Your kernel title does not resolve to the specified id` | none | the slug |
| `code_file` | string | path relative to the pushed folder; must exist | error `A source file must be specified in the metadata` | `station_kernel.py` |
| `language` | string | `python`, `r`, `rmarkdown` | error | `python` |
| `kernel_type` | string | `script`, `notebook` | error | `script` |
| `is_private` | bool | - | `true` | `true` |
| `enable_gpu` | bool | - | `false` | `false` |
| `enable_tpu` | bool | - | `false` | `false` |
| `enable_internet` | bool | needs a phone-verified account (UNVERIFIED, per Kaggle docs) | `true` | `true` |
| `dataset_sources` | list of string | each `<owner>/<slug>` (validated) | `[]` | kit, keys, control datasets |
| `competition_sources` | list of string | competition slugs | `[]` | `[]` |
| `kernel_sources` | list of string | `<owner>/<kernel-slug>`; mounts that kernel's output | `[]` | `[]` |
| `model_sources` | list of string | `<owner>/<model>/<framework>/<variation>/<version>` | `[]` | `[]` |
| `keywords` | list of string | category tags | `[]` | not used |
| `docker_image_pinning_type` | string | `original`, `latest` | none | not used |
| `docker_image` | string | image name | none | not used |
| `machine_shape` | string | accelerator shape; overridden by `push --accelerator` | none | not used (CPU) |

Complete file as generated:

```json
{
  "id": "<OWNER>/<KERNEL_SLUG>",
  "title": "<KERNEL_SLUG>",
  "code_file": "station_kernel.py",
  "language": "python",
  "kernel_type": "script",
  "is_private": true,
  "enable_gpu": false,
  "enable_tpu": false,
  "enable_internet": true,
  "dataset_sources": ["<OWNER>/<KIT_BASE>", "<OWNER>/<KIT_WORK>", "<OWNER>/<KEYS_DATASET>", "<OWNER>/<CONTROL_DATASET>"],
  "competition_sources": [],
  "kernel_sources": [],
  "model_sources": []
}
```

Push flags (CLI 2.2.5): `-p FOLDER`, `-t SECONDS` (per-run limit, never above the platform maximum),
`--accelerator ACC`, `--no-run` (save a version without running it).

## `dataset-metadata.json` (written by `pack_kit.sh`, `make_keys_dataset.sh`, `station_ctl.sh`)

Validation in **kaggle CLI 2.2.5** `datasets create` (MEASURED from source):

| Field | Type | Rule |
|---|---|---|
| `id` | string | `<owner>/<slug>`; slug **6 to 50** characters (`The dataset slug must be between 6 and 50 characters`) |
| `title` | string | 6 to 50 characters |
| `licenses` | list of `{"name": string}` | **exactly one** (`Please specify exactly one license`). `kaggle datasets init` writes `CC0-1.0`; the scripts write `other` (override with `DATASET_LICENSE`). Whether the server accepts `other` is UNVERIFIED. |
| `subtitle` | string, optional | 20 to 80 characters |
| `description`, `keywords`, `resources` | optional | - |

```json
{
  "title": "<SLUG>",
  "id": "<OWNER>/<SLUG>",
  "licenses": [{"name": "other"}]
}
```

`datasets version` reads the same file. Its flags: `-m NOTES` (required), `-p`, `-q`, `-t`, `-r skip|zip|tar`, `-d`
(delete old versions).

## `station_control.json` (control dataset; docs/06 has the semantics)

JSON Schema:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "station_control.json",
  "type": "object",
  "required": ["seq"],
  "properties": {
    "schema":        {"const": 1},
    "seq":           {"type": "integer", "minimum": 0, "description": "must increase; stale documents are ignored"},
    "deadline_utc":  {"type": ["string", "null"], "format": "date-time", "description": "capped at start + MAX_HOURS"},
    "soft_stop_utc": {"type": ["string", "null"], "format": "date-time", "description": "capped at the deadline"},
    "stop_all":      {"type": "boolean", "default": false},
    "messages": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "to", "text"],
        "properties": {
          "id":   {"type": "string", "description": "delivered once per run"},
          "to":   {"type": "string", "description": "worker name or *"},
          "text": {"type": "string"}
        }
      }
    },
    "updated_utc":   {"type": "string", "format": "date-time", "description": "informational"}
  }
}
```

Initial file from `station_ctl.sh init-control`:

```json
{
 "schema": 1,
 "seq": 1,
 "deadline_utc": null,
 "soft_stop_utc": null,
 "stop_all": false,
 "messages": []
}
```

## `status.json` (`/kaggle/working/out/status.json`, outbox, relay)

```json
{
 "utc": "2026-01-01T16:05:00Z",
 "start_utc": "2026-01-01T15:00:00Z",
 "deadline_utc": "2026-01-01T19:00:00Z",
 "soft_stop_utc": "2026-01-01T18:30:00Z",
 "cap_utc": "2026-01-02T02:00:00Z",
 "stop_all": false,
 "control_seq": 4,
 "messages_delivered": ["m2", "m3"],
 "load": ["2.31", "2.15", "1.63"],
 "workers": {
  "W1": {"alive": true,  "rc": null, "status": "<last 300 chars of agents/W1/STATUS.txt>"},
  "W2": {"alive": false, "rc": 0,    "status": "..."}
 },
 "final": true
}
```

`final` appears only in the copy written after the results are packed.

## `STATION` stdout line

```
STATION {"utc": "...", "deadline_utc": "...", "soft_stop_utc": "...", "load": ["..."], "alive": ["W1", "W2"]}
```

Every `STDOUT_PROGRESS_S` seconds. Filter: `kaggle kernels logs <OWNER>/<KERNEL_SLUG> | grep '^STATION '`.

## `setup.log` line format

`HH:MM:SS <message>` (UTC). Key lines:

| Line | Meaning |
|---|---|
| `station start <iso> deadline <iso> cap <iso>` | kernel started |
| `credentials ok: <names>` | names only |
| `extracted <archive> <s> s` | one per kit archive |
| `env probe: ...` | output of `ENV_PROBE` |
| `kit files <n>` | manifest size (results exclude unchanged kit files) |
| `gate compared <n> differences <d> [...]` / `GATE FAILED` | docs/07 |
| `installed worker tool <s> s`, `probe rc <rc> '<out>'` / `PROBE FAILED` | docs/05 |
| `started <name> pid <pid>` | one per worker |
| `control: deadline ... / soft stop ... / stop_all / soft stop lifted / message <id> -> <workers>` | control applied |
| `control download failed rc ...`, `outbox version rc ...` | Kaggle-native channel results (docs/06) |
| `STOP files written`, `deadline: SIGTERM to all workers` | docs/09 |
| `snapshot <n> files`, `results packed <n> files <bytes> bytes`, `done` | results |

## Run output layout (`kaggle kernels output`)

```
run_output/
  <KERNEL_SLUG>.log          # the kernel's stdout/stderr as a JSON array of {"stream_name","time","data"} (MEASURED)
  out/
    setup.log
    status.json
    gate_station.json          # only when GATE_CMD is set
    logs/<WORKER>.log          # stream-json for Claude Code workers
    results.tar.gz             # paths relative to WORKDIR, e.g. agents/W1/REPORT.md, src/...
```

## Worker folder (`WORKDIR/agents/<NAME>/`)

| File | Writer | In results |
|---|---|---|
| `BRIEF.md` | station | no (excluded) |
| `INBOX.md` | station | yes |
| `STOP` | station or worker | no (excluded) |
| `STATUS.txt` | worker | yes |
| `REPORT.md`, `LESSONS.md` | worker | yes |
| anything else matching `RESULT_SUFFIXES` | worker | yes, if under 2 MB |
