# 12 - A free-model worker swarm across many machines

The rest of this repository runs Claude Code workers inside one Kaggle session. This document and the
[swarm/](../swarm/worker.py) code describe a larger pattern built next to it: **many small workers that call free
hosted LLMs**, spread over Kaggle CPU sessions, a free-tier ARM VM, a small always-on VPS and a laptop, kept running
by a hub that needs **no model**, with an optional coordinator model that is called **only when a trigger fires**.

It comes from a run of about a week (2026-11-21 to 2026-11-24) on a decompilation project. Facts carry the README's
tags, read here as: **MEASURED** = measured by us on the date given (on Kaggle or our own hosts), **OBSERVED** = seen
while building it, not re-measured, **UNVERIFIED** = not checked. Provider names and per-provider speeds are left out
on purpose: free offers are time-limited and change; measure your own (section 3).

**What was tested in this generic copy** (2026-11-24): the worker with the example adapter end to end from a clean
clone against a real free provider; the offline suite `tests/test_swarm.py` (stub model server: worker with a
feedback round, probe, host tick with the watchdog, hub tick with ledger and status page, guard, Kaggle scheduler in
`--dry-run`, coordinator triggers). **Not re-tested in this generic copy:** the hub over ssh between real hosts, the
Kaggle scheduler and kernel on real accounts, and the coordinator with a real model call. Those ran in the source
deployment this code was generalised from; treat them as a first version and run them supervised once.

## Quickstart

**Prerequisites.** Python 3.10+ (standard library only), `rsync` and `ssh` for the hub, the `kaggle` CLI (2.x) for
Kaggle. An API key for an OpenAI-compatible endpoint that offers a free model (section 3.3 says where to look).
For Kaggle: **phone (SMS) verification of every account you use.** An unverified account's sessions get **no
internet**, so they cannot reach a hosted model, the relay or an item pool: only offline work runs there (inputs
from datasets, results through `kaggle kernels output`). GPU and TPU quotas also need a verified account (on
2026-11-24: GPU 30 h/week and TPU 20 h/week per verified account, OBSERVED); Kaggle may ask for an extra identity
check before granting TPU. Check internet with a tiny probe kernel that requests internet before relying on an
account (the swarm kernel itself exits with `NO_INTERNET` when it has none).

1. **Clone.**
   ```bash
   git clone https://github.com/kylechoidev/kaggle-station && cd kaggle-station
   ```
2. **Key file** (never in the repository; `.gitignore` also refuses `swarm/providers.json` and `*.key`):
   ```bash
   mkdir -p -m 700 ~/.config/swarm/keys
   (umask 077; cat > ~/.config/swarm/keys/provider-a)      # paste the key, Enter, Ctrl-D
   ```
3. **Define the provider:** `cp swarm/providers.example.json swarm/providers.json` and set `url`, `model` (exactly
   as the provider's `GET /models` lists it), `key` (the path above) and `extra` (the provider's switch for turning
   reasoning off). Delete the entries you do not use.
4. **Probe** (2 small requests per provider; never prints the key):
   ```bash
   python3 -I swarm/probe_providers.py --file swarm/providers.json
   ```
   Expected (values vary):
   ```
   provider             usable tiny_s  speed_s tok/s  reqlim   yield(p/n~close) why
   provider-a           True   1.6     2.2     56.3   1000     -      ok
   CHOICE provider-a
   ```
   `usable False` with a `why` such as `reasoning not switched off (fix "extra")`, `chat HTTP 404`, `cost 0.0002`
   tells you what to fix.
5. **Run one worker locally** with the example workload (write Python functions that pass given unit tests). It
   executes model-written code with a timeout in a temporary folder: fine for a demo, use a container for anything
   more.
   ```bash
   export SWARM_ROOT=$PWD
   python3 -I swarm/worker.py --provider provider-a --providers swarm/providers.json \
       --adapter swarm/adapters/pytests_example.py --agent W1 --threads 2
   ```
   Expected (MEASURED 2026-11-24 with a free provider, from a clean clone; 5-10 s in all):
   ```
   04:29:46 worker W1 start: provider provider-a (model ...), adapter pytests_example.py, phase AB
   04:29:47 phase A p_add: PASS in 1 rounds, 2 s
   04:29:47 phase A gate passed: {'pass': 1}
   04:29:49 w1 t_rle PASS in 1 rounds, submit ok .../work/results/t_rle.json
   ...
   04:29:51 worker done: {'answers': 5, 'passes': 5, 'submits': 4, 'giveups': 0, 'errors': 0, 'stop': None}
   ```
   Results: `work/results/*.json`; status: `work/agents/W1/status.json`; give-ups with reasons:
   `work/results/giveup/`. Run it again and it says `no more items` (the example pool is used up; delete
   `work/results/` to reset).
6. **Your own workload:** copy `swarm/adapters/pytests_example.py` (or the decompilation skeleton
   `swarm/adapters/decomp_pool_skeleton.py`) and implement `get_item`, `build_prompt`, `verify`, `submit`,
   `give_up`, `release` (section 4). Mini yield test of a provider on your practice items:
   ```bash
   python3 -I swarm/probe_providers.py --file swarm/providers.json --only provider-a \
       --yield-cmd 'python3 -I swarm/yield_test.py --provider {provider} --providers {providers}'
   ```
7. **Hub on a VPS** (always on): clone to the same absolute path on every host (or set `root` per host), then on the
   hub `mkdir -p hub && cp swarm/hub/config.example.json hub/config.json && cp swarm/providers.json hub/providers.json`,
   edit `hub/config.json` (hosts, workers, singletons), and add to its crontab:
   ```
   */5 * * * * cd /ABS/SWARM_ROOT && SWARM_ROOT=/ABS/SWARM_ROOT /usr/bin/python3 -I swarm/hub/tick.py >> hub/log/cron.log 2>&1
   ```
   The first tick starts every registered worker with `"watch": true` on the hub and on ssh-reachable hosts
   (`hub/hosts/<host>.json` shows `"decision": "restarted (previous stop: crash)"` for a worker that never ran) and
   writes `hub/www/index.html`. A laptop the hub cannot reach runs `swarm/hub/push_host.sh <hub-ssh> <hub-root>`
   every 5 min from a timer (its report is the "owner present" heartbeat).
8. **Kaggle** (verified accounts only): keys dataset with `scripts/make_keys_dataset.sh` (docs/02), the code with
   `swarm/kaggle/make_code_bundle.sh <user>/swarm-code swarm/providers.json --create`, then
   `mkdir -p kaggle && cp swarm/kaggle/sched.example.json kaggle/sched.json`, edit it, try
   `python3 -I swarm/kaggle/kaggle_sched.py --dry-run` (expect one `DRY would push` line per free slot), and run it
   from cron every 3-5 min behind `swarm/hub/guard.py kaggle_sched`.
9. **Coordinator (optional, spends model credits):** fill `swarm/coord/brief_template.md` into
   `hub/coord/brief.md`, test the triggers with `COORD_DRY=1 bash swarm/coord/patrol.sh` (no model call), then run
   `tmux new -d -s coord 'SWARM_ROOT=/ABS/SWARM_ROOT bash swarm/coord/patrol.sh'` on the host that holds the
   copied hub status.

Sections: 1 the pattern, 2 hosts and data flow, 3 the provider slot and the deal hunt, 4 the worker loop and
adapters, 5 the hub, 6 Kaggle scaling, 7 the trigger-only coordinator, 8 stopping things, 9 pitfalls, 10 file map.

## 1. The pattern

A **worker** repeats one loop:

```
take an item  ->  ask the model for a candidate  ->  run the CHECKER on it  ->  feed the checker's complaint back
(claim / queue)                                      (the only judge)           for a few rounds
             ->  SUBMIT only what the checker accepts, otherwise GIVE UP with a one-line reason (and release the item)
```

The model is cheap and fallible; the checker is strict and local. That is what makes free models usable: a bad
answer costs one request, never a wrong result. Example workloads:

| Workload | Item | Checker | "Submit" |
|---|---|---|---|
| Matching decompilation | one function of a binary | compile with the original compiler and flags, compare the machine code byte for byte | send the source to the project's pool |
| Code port (e.g. to Rust) | one module or function | build + the ported unit tests (or a behaviour comparison against the original) | open a commit / merge request |
| Data extraction | one document or page | a schema validator plus cross-field rules | append the record to the dataset |

What matters for the pattern: the checker is deterministic, runs on every host with identical results (prove it,
section 5.5), and gives feedback a model can act on (a diff, the first errors, the failing test).

## 2. Hosts and data flow

| Host | Typical size | Role |
|---|---|---|
| Laptop | the owner's machine; off at times | interactive coordinator session, local dashboard, a few workers, code deploys |
| Small VPS (always on) | 2 vCPU / 3-4 GB | **the hub**: master config, results ledger, singletons (schedulers, queue submitters), status page, Kaggle CLI and relay; one worker at most |
| Free-tier ARM VM (always on) | 2 OCPU / 12 GB | most local workers; Claude Code for the cloud coordinator. An x86 toolchain runs under box64 + Wine (MEASURED: identical verdicts and object hashes on 156 sample items compared with x86) |
| Kaggle CPU sessions | 4 vCPU / ~30 GB, 12 h max | many workers per account (section 6); hosted model, so no GPU needed |

Two facts about reachability decided the design (OBSERVED 2026-11-24, our network): the laptop reaches the VPS and
(through it) the ARM VM; the VPS reaches the ARM VM; **the ARM VM reaches neither**. So the VPS is the hub and
drives the ARM VM over ssh; anything running on the ARM VM acts on the hub only through request files the hub pulls.

**Path identity:** every host has the same absolute project path (a symlink to wherever the tree really lives), so
every script runs unchanged everywhere.

```
                    item source (pool API / queue)       verifier/toolchain releases
                       ^     ^      ^      ^                      ^
       claims, submits |     |      |      |  each host updates   | (status hash + download,
       (each host,     |     |      |      |  its own copy        |  recheck, swap or roll back)
        own key copy)  |     |      |      |                      |
   [laptop workers] [VPS worker + singletons] [ARM VM workers] [Kaggle sessions]
          |  ^             |   ^                 ^   |               | rsync every 60 s
          |  | ledger,     |   | hub tick         |   | ledger export  v
          |  | config,     v   | (cron, 5 min)    |   v               relay folder on the VPS
          |  | status   +--------------------------------------+         |
          +--+--------> | HUB (VPS)                            |   Kaggle schedulers (cron)
   laptop timer:        |  config.json  providers.json         |
   push report          |  ledger/  hosts/<host>.json          |
   (= heartbeat) and    |  alerts/  coord/  www/ (status page) |
   ledger export, pull  +--------------------------------------+
   the rest
```

## 3. The provider slot and the deal hunt

### 3.1 A provider is five facts
```json
"name": {"url": "https://<provider>/v1",       "OpenAI-compatible base: POST <url>/chat/completions, GET <url>/models"
         "model": "<model id>",                "exactly as GET /models lists it; prefixes differ between providers"
         "key": "~/.config/<dir>/<file>",       "PATH of a bearer key file (mode 600), never the key"
         "extra": {"...": "..."},              "merged into every request: switch reasoning OFF here"
         "attr": "<credit text>"}
```
Keep the list in one file on the hub and distribute it; workers take `--provider <name>`. See
[swarm/providers.example.json](../swarm/providers.example.json).

Rules that held for every provider we tried (MEASURED 2026-11-24 unless marked):
- **The same model behind two endpoints is two different providers.** Model ids differed (one wanted a bare id, the
  other an `org/` prefix; the wrong form gave HTTP 404), and so did the reasoning switch (`reasoning_effort: "none"`
  on one, `reasoning: {enabled: false}` on the other; a third form had no effect on the first, OBSERVED by another
  team). A wrong switch silently spends the answer budget on reasoning; the probe flags it when
  `reasoning_content` comes back.
- **Speed decides yield, not the model name.** The same free model on two endpoints: about 30 s per item (4 rounds
  including checks) on one, 40-70 s on the other; in the same 15-minute window the faster one produced accepted
  results from several workers and the slower one none. We moved every worker to the faster endpoint and kept the
  slower as a tested fallback.
- **Rate limits are per key, not per worker.** Read the `x-ratelimit-*` / `ratelimit` headers. One provider
  advertised a short per-key request window (a few hundred requests) shared by every worker and by another project
  on the same key; another advertised per-minute and per-hour request and token budgets. Adding workers past the
  window adds HTTP 429s, not throughput.
- **Cost must stay 0.** Workers stop when a response reports `usage.cost` > 0, or on HTTP 401/402/403/404 (key
  revoked, payment required, model removed). Those stops are never auto-restarted (section 5.3): they mean the deal
  ended.

### 3.2 Probe and rank: `swarm/probe_providers.py`
```bash
python3 -I swarm/probe_providers.py --file swarm/providers.json             # every entry
python3 -I swarm/probe_providers.py --file swarm/providers.json --only a,b \
        --yield-cmd 'python3 -I swarm/yield_test.py --provider {provider} --providers {providers}'
```
Per provider: key file present; `GET /models` (listed? price 0 where the provider publishes prices); a tiny
request (HTTP code, latency, rate-limit headers, `usage.cost`); a ~120-token request (seconds, tokens/s, finish
reason, reasoning leak, empty answer). `--yield-cmd` runs your own **mini yield test**: `swarm/yield_test.py` runs the worker's phase A on the adapter's
practice items (items you already know the answer to; no claims, no submits; it stops at the first pass, like the
phase A gate, so it measures "can this provider pass at all" more than a rate) and prints a JSON line
`{"passed": N, "total": M, "closest": X}`; `closest` is any "how far off" number where lower is better (we used the
sum of differing instructions of the best attempts). Ranking: usable first (HTTP 200, listed or no listing, price
and cost 0, no reasoning leak, non-empty answers), then passed, then closest, then seconds per answer, then the
request limit. The last line is always `CHOICE <name>`. Cost: 2 small requests per provider plus your yield test.
The script never prints keys and masks a key if a provider echoes it.

MEASURED 2026-11-24 (two endpoints of one free model): tiny request 1.6-2.4 s, 120-token answer 2.2-3.5 s
(35-56 tokens/s); a 3-item, 2-round yield test took 30 s and passed 0 of 3 (closest 2, 4 and 7 instructions off):
coarse, but it proves the whole loop works with the provider.

### 3.3 The deal hunt: at every start, and whenever a deal ends
1. **Look (read only):** OpenRouter's model list filtered to `:free` ids (its `/models` gives
   `pricing.prompt` / `pricing.completion` = "0"); providers' pricing pages and changelogs; inference providers that
   run free promotions; Kaggle Models (a model that fits a free Kaggle GPU or TPU session and that you serve
   yourself; see [ARahim3/kaggle-tpu-lab](https://github.com/ARahim3/kaggle-tpu-lab) for a TPU serving path);
   your own team's provider notes.
2. **Key:** the owner creates the account and key (never a script or an agent) and puts the key file on each host
   that will use it; for Kaggle into the private keys dataset (docs/02).
3. **Define** the entry in the hub's providers file.
4. **Probe**, then the yield test on the best two. Reject anything with price or cost above 0, a reasoning leak you
   cannot switch off, or a request budget far below what the workers need (a fast provider took roughly one request
   per 5-10 s per worker, MEASURED).
5. **Switch every worker** (section 5.3: the hub restarts each one on the new provider).

## 4. The worker loop and adapters

`swarm/worker.py` owns the model calls, rounds, stop flags and the status file; the workload is an **adapter** file
with a class `Adapter`:

| Method | Called | Example adapter (`pytests_example.py`) | Decompilation skeleton (`decomp_pool_skeleton.py`) |
|---|---|---|---|
| `practice_items(n)` | phase A | tasks marked `practice` | TODO: functions you already matched, with their packs |
| `get_item()` | phase B, per thread | next untaken task (a file under `flock` = a tiny pool) | `claim` call on the pool API (TODO) |
| `build_prompt(item, history)` | each round | signature, description, tests; last failure as feedback | listing, flags; checker diff as feedback |
| `extract(reply)` | optional | default: longest fenced code block | default |
| `verify(item, cand) -> (ok, feedback, score)` | each answer | run the tests (`python3 -I`, temp dir, 10 s timeout) | the project's checker command (TODO output format) |
| `submit(item, cand)` | on a pass | write `work/results/<id>.json` | `submit` call (TODO), after team-wide guards |
| `give_up(item, best, reason)` | no pass | write `work/results/giveup/<id>.json` | `giveup` call with the best attempt (TODO) |
| `release(item)` | exit / error | un-take the task | give up with "worker stopped" |

Rounds: fresh answer, feedback on the last failure, a hotter fresh answer, feedback again (temperatures 0.2, 0.2,
0.7, 0.4); duplicates of an earlier answer are rejected without running the checker. `--adapter-arg KEY=VALUE`
passes settings to the adapter.

### 4.1 How the loop behaves
- **Phase A (practice, offline):** the worker solves a few random items in a sandbox (synthesised inputs, no claims)
  and repeats until its first clean pass. It proves the provider, the prompt and the checker on that host before
  any real claim. Hosts and models that never pass phase A never claim.
- **Phase B (live):** claim one item per worker thread, solve in the real inputs, run every pre-submit guard
  (refused patterns, a uniqueness check against all results of the whole team, section 5.4), submit only a clean
  pass, otherwise give up with the best attempt and a one-line reason. At most one claim per thread; none left
  open at exit (SIGTERM releases them).
- **Shared stop flags** every worker polls between items: per worker (`STOP`), project-wide (daily cap reached,
  verifier stale, remote halt). A daily-cap refusal writes the cap flag at once.
- **Status file** per worker (`status.json`: phase, answers, passes, submits, give-ups, errors, `stop` reason,
  seconds per item, provider, last HTTP code, last rate-limit headers) plus an events log. Everything else reads
  these: the watchdog, the status page, the coordinator.
- Optional: post short give-up notes (words only, never code) to a shared notes service so other workers and teams
  do not repeat the same dead ends; rate-limit the posts (we used one per minute per worker).

## 5. The hub: always on, no model, no credits

### 5.1 What the laptop used to do, and where it went
| When the laptop is off, this stops | Moved to |
|---|---|
| the queue submitter for a rule-based generator's output | hub singleton daemon (state copied once) |
| the Kaggle shard scheduler | hub cron, guarded so it runs only on its assigned host |
| the "what is still open" snapshot | hub periodic job (15 min), copied to the other hosts |
| verifier/toolchain freshness and updates | every host updates itself (5.5) |
| team-wide uniqueness checks (they only saw the local host's results) | the results ledger (5.4) |
| the dashboard | a static status page built by the hub every 5 min, served on loopback, reached by an ssh tunnel |
| the interactive coordinator | the trigger-only cloud coordinator (section 7), with the owner's approval |
| laptop workers | nothing: they just stop |

### 5.2 Pieces
- **Hub tick** (cron every 5 min on the VPS, under `flock`): apply coordinator requests to the master config; decide
  which singletons may start; run the per-host tick locally and on the ARM VM over ssh; merge the ledger; copy
  config, providers, the ledger, the laptop heartbeat and the open snapshot to the ARM VM; pull its coordinator log
  and alerts; build the status page. A `HUB_STOP` file makes it do nothing.
- **Per-host tick** (every host): verifier update check (at most every 10 min), ledger export, singleton
  enforcement, the worker watchdog; prints a JSON report that becomes `hosts/<host>.json`.
- **Laptop timer** (every 5 min; systemd user timer because user cron was not available there, OBSERVED): pull
  config and providers, run the per-host tick, push the report (this is the **heartbeat**) and the ledger export,
  pull the ledger, status page, coordinator log and snapshot.
- On the ARM VM there is no cron or linger in our setup (OBSERVED), so nothing is scheduled there: the hub drives it.

### 5.3 Singletons and the watchdog
- **One assigned host per singleton**, written in the master config. A daemon starts only on that host and only if
  no other host's report from the last 20 minutes shows it running. Found on a non-assigned host, it gets its STOP
  file with a `hub:` marker (graceful); without a STOP mechanism it gets SIGTERM. A STOP file without the marker is a
  human's and is respected. Cron-type singletons run behind a guard that exits non-zero unless the config assigns
  them to this host (fails closed). Moving one: STOP it where it runs, wait for it to exit (MEASURED: it halted
  within 2 minutes, after the item in flight), copy its state, then change the assigned host.
- **Watchdog**, per worker marked `watch: true`, on its own host:

  | Last stop reason | Action |
  |---|---|
  | crash (status phase not finished, no reason) | restart after 10 min backoff |
  | reboot (SIGTERM older than the host's boot time) | restart |
  | verifier stale (only once the flag is gone), provider switch | restart |
  | LLM down, practice set exhausted | restart after 30 min |
  | `STOP`, `STOP_ALL`, daily cap, remote halt, deal ended (401/402/403/404), cost > 0, unknown | **never**: write an alert |
  | any stop flag present | hold |

  At most 12 restarts per worker per day. Workers are found by reading `/proc/*/cmdline` (script basename plus
  `--agent <name>`), never with `pkill -f` / `pgrep -f`, whose patterns also match the shell that carries them
  (section 9). MEASURED 2026-11-24 on a scratch worker: SIGKILL -> restarted; practice exhausted -> 30 min backoff;
  coordinator STOP -> held; provider switch -> restarted on the new provider.
- **Provider switch:** change the worker's provider in the master config (or a coordinator request). The watchdog
  places a `hub:` STOP on each running worker whose `--provider` differs; the worker finishes its item, releases its
  claim and exits; the next tick clears that STOP and starts it on the new provider. First test lesson: the switched
  worker's own stop reason then reads `STOP`, which must not be mistaken for a human stop.

### 5.4 Results ledger
Each host exports its own results as one small JSON per item (`{item, result text, model, host, time}`) to an
outgoing folder; the hub merges all hosts into `ledger/` (newest wins per item) and copies it back to every host.
Team-wide pre-submit checks (in our case: one name per item across all submissions) read the ledger as well as local
results. MEASURED before the ledger: three hosts each saw only their own share of the team's results, so a
uniqueness check passed on one host for a name another host had already used. After the ledger the same check on
the ARM VM caught a name used only by a laptop result. First copies are slow (about 6,800 files in ~2 min from the
ARM VM over ssh; ~5,400 files from the laptop took over 10 min over its link), later passes copy only new files.

### 5.5 Self-updating verifier/toolchain, per host
If the project republishes its checker during the day, every host must notice and update without the laptop:
1. Compare the published version (a hash in a status endpoint, or a release tag) with the local files; a cheap
   HEAD/ETag works as a change signal only (MEASURED: our server's ETag was not the content md5).
2. On a difference: set the project-wide **stale flag** (every worker and submitter holds), download, verify the
   hashes, unpack into a new folder, rename the old one with a timestamp, swap.
3. **Re-check a sample of past accepted results** with the new checker on this host. Clear the flag only if (almost)
   all still pass; otherwise swap the old one back, keep the flag with the reason, and alert: a human or the
   coordinator decides. MEASURED in a sandbox: failing recheck -> rolled back and held; passing recheck (6/6) ->
   installed and cleared in ~30 s.
4. Workers also compare each claim's stated checker version with theirs and stop on a mismatch; the watchdog
   restarts them once the flag is cleared.
Before trusting a new host at all, run an **equivalence test**: the same sample through the checker on both hosts
must give identical verdicts and identical normalised outputs (we normalised compiler-generated anonymous names that
change on every compile, OBSERVED). See docs/07 for the gate inside a Kaggle session.

### 5.6 Status page
A static HTML page plus `status.json`, rebuilt every tick: each host's report age, load and memory, flags; each
worker (up/down, provider, phase, passes/submits/give-ups, seconds per item, stop reason, watchdog decision);
singletons; the pool account (submissions today, open claims, pauses, strikes); results per host in the last hour
and day from the ledger; Kaggle lanes; alerts; the coordinator log tail. Served by `python3 -m http.server --bind
127.0.0.1 <PORT>` (kept alive as a hub singleton); from the laptop through `ssh -L`.

## 6. Kaggle at scale

- **Internet needs a phone-verified account.** Kaggle gives internet to sessions only on accounts that passed phone
  (SMS) verification. Without it a session cannot reach a hosted model API, the relay or an item pool, so only
  offline work runs there (inputs from datasets, results through kernel output): unverified accounts are good for
  offline shards only. GPU and TPU quotas also need a verified account (2026-11-24: GPU 30 h/week, TPU 20 h/week per
  verified account; Kaggle may ask for an extra identity check before TPU). Probe each account with a tiny kernel
  that requests internet before relying on it; `swarm/kaggle/swarm_kernel.py` exits with `NO_INTERNET` when it
  has none.
- **The scheduler** (`swarm/kaggle/kaggle_sched.py`, cron on the hub, one Kaggle login per account through
  `HOME=<account home>`): keeps up to `slots` (default 5) sessions per account running as kernels
  `<slug_prefix>-1..5`, counting other projects' running kernels against the cap; renders each slot's kernel with its
  own worker name and relay folder (`<relay_prefix>-<user>-<n>`), saves state right after each push, and has a
  **stale-slot watchdog** (RUNNING but no relay status for `stale_min`: alert; with `"stale_action": "delete"` the
  second stale pass deletes the kernel). `kaggle/STOP_ALL` containing **`pause`** launches nothing and lets running
  sessions finish; **`yield`** also writes STOP_ALL into every slot's relay inbox, so the sessions finish their item,
  release it and exit within minutes (to hand the slots to another project).
- **The kernel** (`swarm/kaggle/swarm_kernel.py`): unpacks the code dataset (`swarm_code.tgz.bin`), writes key
  files from the keys dataset (mode 600), checks internet, runs one worker (with `--threads`) until the deadline,
  rsyncs the worker folder to the relay every 60 s and pulls the relay inbox.
- **Hosted model = CPU sessions.** One session per account was a leftover from serving models on GPUs. With a hosted
  model, fill the CPU slots: MEASURED 2026-11-23, the 6th concurrent push on one account failed at once with
  `Kernel push error: Maximum batch CPU session count of 5 reached.` (no queueing); GPU sessions are capped
  separately (2, MEASURED) and did not count against the 5; a queued TPU version held the account's single TPU slot
  (`Maximum batch TPU session count of 1 reached.`).
- **Shared accounts:** if other projects use the same accounts, check `kaggle kernels list --mine` (and its owner
  column, below) before filling slots, and agree a priority (we gave short batch shards priority over long workers).
- **All workers on one provider key share its rate limit**, Kaggle or not.
- **Relay:** each session rsyncs its outbox to the VPS every 60 s (appendix A); schedulers on the VPS read the relay,
  archive finished runs, and relaunch. Save scheduler state right after each push (OBSERVED: a crash between a push
  and the state save made the next pass push the same account again).
- **Keys** travel in the account's private keys dataset (docs/02), never in the kernel or the code dataset.
- **Start latency** (MEASURED): CPU pushes were RUNNING within about a minute; GPU pushes waited 13-30 min in the
  queue while showing RUNNING; a TPU push stayed QUEUED for over 2 h.
- **Completion before the last relay** (MEASURED): `COMPLETE` arrived while the relay still held the previous phase's
  summary; one shard was wrongly retried. Read `kaggle kernels output` before deciding a run failed.
- **Silent hardware downgrade** (MEASURED): TPU requests on some accounts ran on the CPU image (`jax` saw 1 cpu
  device) although the push was accepted; per account, not per metadata. Check the device at start and fail loudly.

## 7. The trigger-only cloud coordinator

A Claude Code instance on the ARM VM (its own login there) that is **called by a shell loop only when a trigger
fires**, does one patrol, writes a log entry and exits. Spending is bounded by design.
`swarm/coord/patrol.sh` is that loop (triggers in `swarm/coord/triggers.py`, brief in
`swarm/coord/brief_template.md`); the model command is `COORD_CMD` (default: Claude Code headless; any CLI that reads
the prompt from stdin works).

- **Watches** (copied to the ARM VM by the hub every tick): `status.json` (hub age, laptop heartbeat, workers, flags,
  account health), alerts, workers' events logs, its own log.
- **Triggers:** a new alert; a watched worker down more than 15 min with a "not restarted" / "cap" / "held"
  decision; the stale flag older than 30 min; the hub status older than 20 min; an account pause, strike or new
  problem; a deal-ended or cost stop; a routine patrol every 6 h. Each trigger at most once per hour unless it
  changes; at most N calls a day (we chose 8), each with a wall-clock timeout.
- **Duties:** restart workers the watchdog will not (never one a human stopped); react to a stale checker (run the
  updater; never force a version that failed its recheck); detect a deal ending, re-run the probe and deal hunt, and
  switch every worker; release claims no running process holds; stop workers on account trouble; log every patrol.
- **Request files instead of access:** the ARM VM cannot reach the hub, and that is useful. The coordinator writes
  `requests/<time>-<action>.json`; the hub pulls and applies only an allow-list (set provider, watch on/off,
  start/stop worker, add worker up to a per-host cap, stop/resume the Kaggle scheduler (resume only what the
  coordinator stopped), update the checker now, define a provider (https URL, key **path** only), note) and returns
  each result. The master config stays single-writer.
- **Handback by heartbeat:** when the laptop's report is younger than 15 min, the loop runs one last patrol that
  writes `HANDBACK.md` (what happened, requests and results, what is held for a human), then stops calling the model
  until the laptop is gone again. The laptop timer pulls the coordinator folder home; the laptop session reads it
  first.
- **Dry test:** a `COORD_DRY=1` mode replaces the model call with `echo`, so the triggers can be tested for free
  (we did, with a staged alert and an old heartbeat, and with a fresh heartbeat: no call).
- Launch it in `tmux`, with `--model`, `--effort`, `--permission-mode acceptEdits`, a narrow `--allowedTools`, and
  `--max-budget-usd` (applies to API billing; UNVERIFIED for subscription logins). See docs/05 for headless flags.

## 8. Stopping things

| What | How |
|---|---|
| one worker | its `STOP` file (finishes the item, releases the claim, exits; the watchdog holds) |
| every worker on a host | the project-wide flags (daily cap, stale checker, remote halt) |
| a Kaggle session | the station's control file (`stop_all`, docs/06) |
| a Kaggle scheduler | its `STOP` file on the VPS |
| a singleton | its STOP file without the `hub:` marker (stays down) |
| the hub | `HUB_STOP`; remove the cron lines to uninstall (back up the crontab first) |
| the coordinator | a `COORD_STOP` file, or kill its tmux session |

## 9. Pitfalls (dated observations)

- **`ssh host 'pkill -f "<pattern>"'` kills its own remote shell** when the pattern appears on that shell's command
  line (ssh exit 255), MEASURED twice. Use STOP files, `/proc` cmdline matching, or `pgrep -f '[p]attern'` style
  patterns the command line does not contain, then kill by PID.
- **Kaggle CLI 2.2.x ignored `KAGGLE_CONFIG_DIR` for `access_token`** and silently fell back to `~/.kaggle` (another
  account). Always check the owner column of `kaggle kernels list --mine`. MEASURED.
- **A dataset file named `*.tar.gz` was not found by name** inside the session; the same archive renamed `*.bin` was
  (OBSERVED once).
- **Pushing a new version does not cancel a running one**; `kaggle kernels delete <owner>/<slug> -y` did (MEASURED).
- **First requests to a freshly loaded local model are slow** (2.7 tokens/s on the first call, about 40 later,
  MEASURED with llama.cpp on 2x T4); measure after warm-up. **Replacing `LD_LIBRARY_PATH`** made llama.cpp run on
  the CPU with 0 MiB VRAM used and no error (MEASURED): append to it, and treat 0 MiB VRAM after load as a failure.
- **A stale flag raised from old evidence:** a host that no longer claims kept comparing against old claim packets
  and raised false "checker stale" alarms; compare against the published version (status endpoint), not the newest
  local packet (OBSERVED, three times in one day).
- **A code push to the shared package changes its version stamp at once,** and remote hosts refusing to work "while
  behind" stop until they pull: push and pull back to back (OBSERVED).
- **Distribution packages lag:** an old box64 package could not run a new-style WoW64 Wine; a source build of a
  current box64 release with a matching Wine build worked, a newer Wine aborted, an older one killed the compiler
  after a good compile (OBSERVED; pin versions that pass your equivalence test).
- **Daily caps:** the first daily-cap refusal should stop every worker on the account; nothing should clear that flag
  automatically.
- **Same model, different endpoint, different results** (section 3.1): probe each endpoint, not each model.

## 10. Adapting it, and the file map

Keep: the provider file and probe, the phase A gate, the checker as the only judge, the shared stop flags, the hub
(master config, singletons with one assigned host and `hub:` markers, the watchdog table, the ledger, per-host
self-update with recheck and rollback, the status page), request files for the coordinator, handback by heartbeat.
Change: the adapter (item source, prompt, checker, submit), the published-version signal for self-update (for a code
port: the pinned toolchain file; for extraction: the validator's schema version), the ledger glob, the host list.

| Path | Runs on | What |
|---|---|---|
| [swarm/worker.py](../swarm/worker.py) | any host, Kaggle | the worker loop (phases A/B, rounds, stop flags, status) |
| [swarm/adapters/pytests_example.py](../swarm/adapters/pytests_example.py) | - | runnable example workload (+ `tasks_example.json`) |
| [swarm/adapters/decomp_pool_skeleton.py](../swarm/adapters/decomp_pool_skeleton.py) | - | skeleton for a byte-matching decompilation pool (TODOs) |
| [swarm/probe_providers.py](../swarm/probe_providers.py), [swarm/yield_test.py](../swarm/yield_test.py) | home | probe and rank providers; mini yield test |
| [swarm/providers.example.json](../swarm/providers.example.json) | - | provider entries (placeholders) |
| [swarm/hub/tick.py](../swarm/hub/tick.py) | hub, cron | requests, ssh ticks, ledger merge, distribution, status page |
| [swarm/hub/host.py](../swarm/hub/host.py) | every host | per-host tick: self-update, ledger export, singletons, watchdog |
| [swarm/hub/guard.py](../swarm/hub/guard.py), [swarm/hub/push_host.sh](../swarm/hub/push_host.sh), [swarm/hub/self_update.py](../swarm/hub/self_update.py) | hosts | cron guard; laptop push; verifier self-update |
| [swarm/hub/config.example.json](../swarm/hub/config.example.json) | - | the one config file (paths relative to `SWARM_ROOT`) |
| [swarm/kaggle/kaggle_sched.py](../swarm/kaggle/kaggle_sched.py), [swarm/kaggle/swarm_kernel.py](../swarm/kaggle/swarm_kernel.py), [swarm/kaggle/make_code_bundle.sh](../swarm/kaggle/make_code_bundle.sh), [swarm/kaggle/sched.example.json](../swarm/kaggle/sched.example.json) | hub / Kaggle | multi-slot scheduler, kernel wrapper, code dataset |
| [swarm/coord/patrol.sh](../swarm/coord/patrol.sh), [swarm/coord/triggers.py](../swarm/coord/triggers.py), [swarm/coord/brief_template.md](../swarm/coord/brief_template.md) | coordinator host | trigger-only coordinator |
| [tests/test_swarm.py](../tests/test_swarm.py) | dev | offline tests with a stub model server |
