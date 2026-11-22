# 02 - Credentials

## What the station reads

The kernel looks up each credential **by name**: first a file of that name anywhere under `/kaggle/input`, then a
Kaggle Secret of that name. Values are never logged; `setup.log` lists only the names found.

| Name | Required | Used for | Where it goes in the session |
|---|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | yes (default `REQUIRED_CREDENTIALS`) | Claude Code auth; token from `claude setup-token` | workers' environment (`WORKER_ENV_CREDENTIALS`) |
| `PROJECT_API_KEY` | no | whatever service your workers use | file `/root/.config/project/api_key`, mode 0600 (`FILE_CREDENTIALS`) |
| `KAGGLE_JSON` | no | the station's own `kaggle` calls (control download, outbox) if built-in session auth is not enough | `/root/.station/kaggle/kaggle.json`, 0600, `KAGGLE_CONFIG_DIR` for station calls only |
| `RELAY_SSH_KEY` | appendix A only | rsync to your own server | `/root/.station/relay_key`, 0600 |

## Choice: keys dataset (default) or Kaggle Secrets

| | **Keys dataset** (default) | **Kaggle Secrets** |
|---|---|---|
| How | files uploaded from the home computer with `scripts/make_keys_dataset.sh`; listed in `dataset_sources` | web editor: Add-ons, Secrets, attach to this notebook; read with `UserSecretsClient().get_secret(name)` |
| Works for CLI-pushed runs | **yes** (MEASURED: the kernel found and used all three credentials) | **no**: `get_secret` failed with HTTP 400 Bad Request, surfaced as `ConnectionError: Connection error trying to communicate with service` (OBSERVED) |
| Works for runs started in the editor ("Save Version") | yes | yes (OBSERVED) |
| Start, restart and stop from the CLI only | yes | no: every run needs the browser |
| CLI can attach it | yes (`dataset_sources`) | no command for it (MEASURED, CLI 2.0.2 and 2.2.5) |
| Mixing with CLI pushes | - | pushing with the CLI while the editor is open makes the editor's next save fail with `ConcurrencyViolation Sequence number must match Draft record`; reload the editor first (OBSERVED) |
| Copies kept by Kaggle | **every dataset version** keeps its files until the dataset is deleted | not versioned |
| Readable by | **anyone signed in to that Kaggle account**; collaborators you add to the dataset; every process in a run that attaches it (MEASURED: files mounted `rw-rw-rw-`) | the account owner in the editor; every process in a run once fetched |
| Rotation | revoke the credential, `kaggle datasets delete <OWNER>/<KEYS_DATASET> -y`, create the dataset again | edit in the editor |

The template supports both. `credential()` tries the file first and then the Secret, so you only choose where the
value lives.

## Exposure, plainly

| Who | Keys dataset | Kaggle Secret |
|---|---|---|
| You, signed in to Kaggle | can download it | can see and edit it |
| Someone else signed in to the same account (a shared account) | **can download it** | can see it in the editor and attach it |
| Kaggle (the platform) | stores it | stores it |
| Every agent in the run (root, `Bash` pre-approved) | can read `/kaggle/input/**` | can call `get_secret` in an editor run, and can read process environments as root |
| Every agent in the run, through the session's own Kaggle login | can probably download your other datasets too (read access MEASURED for `kernels list`; dataset download UNVERIFIED) | same |
| The public | no, as long as the dataset stays private and is never forked or made public | no |

What follows from that: use a Kaggle account that you alone control. Give the station a Claude token used only
for stations, and revoke it after a campaign. Keep the keys dataset separate: never inside the kit, never public.

## Handling rules (implemented in `scripts/station_kernel.py`)

| Rule | Why |
|---|---|
| Never print a credential, its length or a prefix; log only names | the run output and any channel leave the session |
| Pass the Claude token only through `env=`, never on a command line | argv is visible to every process (`ps`) |
| Write file credentials with mode 0600, outside `/kaggle/working` | `/kaggle/working` becomes the run output |
| Drop `KAGGLE_USER_SECRETS_TOKEN`, `KAGGLE_DATA_PROXY_TOKEN`, `KAGGLE_API_V1_TOKEN` from worker environments (`DROP_ENV_PREFIXES`) | hygiene only: root can still read them from `/proc/1/environ`. Whether this stops a worker's `kaggle` CLI from authenticating is UNVERIFIED |
| The brief tells workers never to print credentials or copy them into results | prevents accidents, not attacks |
| `RESULT_EXCLUDE_GLOBS` drops `*token*`, `*secret*`, `*api_key*`, `*.key`, `*.pem` from results | a second net |

MEASURED: Claude Code did not pass `CLAUDE_CODE_OAUTH_TOKEN` on to its Bash tool's environment (the name was absent
from a worker's `env`). Do not rely on that.

## Rotation

| Credential | How |
|---|---|
| Claude token | `claude setup-token` makes a new long-lived token (OBSERVED: one year). Revoke old ones in your Claude account (exact menu UNVERIFIED). |
| Keys dataset | after any rotation: `kaggle datasets delete <OWNER>/<KEYS_DATASET> -y`, then `make_keys_dataset.sh` again (old versions keep old values). `kaggle datasets version -d` ("Delete old versions", CLI 2.2.5 help) is an alternative; whether deleted versions are fully gone is UNVERIFIED. |
| `PROJECT_API_KEY` | per your service |
| `KAGGLE_JSON` | expire the token in Kaggle settings and create a new one |
| Relay key | delete its `authorized_keys` line on your server |
