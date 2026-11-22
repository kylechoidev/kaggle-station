# 05 - Claude Code headless, several at once

The kernel runs any `WORKER_CMD`. This page covers the Claude Code preset, which is what the measured run used.

## Install and probe

| Step | Command | Measured |
|---|---|---|
| install | `curl -fsSL https://claude.ai/install.sh \| bash` (`INSTALL_CMD`) | Claude Code 2.1.330; installs to `~/.local/share/claude/versions/<ver>` with `~/.local/bin/claude` as a symlink; about 364 MB; no Node.js |
| PATH | `EXTRA_PATH = ['/root/.local/bin']` | - |
| auth | env `CLAUDE_CODE_OAUTH_TOKEN=<token from claude setup-token>` | the `init` event reports `"apiKeySource": "none"` (subscription OAuth, no API key) |
| probe | `claude -p "Reply with the single word OK" --model opus` (`PROBE_CMD`) | install + probe: 23 s |
| runs as root | yes, no warnings that blocked work | MEASURED |

The probe catches a bad or revoked token, missing internet and an exhausted usage limit before any worker starts.

## Worker command

```python
WORKER_CMD = ['claude', '-p', '{BRIEF}', '--model', 'opus',
              '--output-format', 'stream-json', '--verbose',
              '--permission-mode', 'acceptEdits',
              '--allowedTools', 'Bash,Read,Write,Edit,Glob,Grep']
```

| Flag | Effect | Tag |
|---|---|---|
| `-p <prompt>` | headless (print) mode: no TTY; runs the brief to completion, then exits | MEASURED |
| `--model opus` | model alias | MEASURED |
| `--output-format stream-json` | one JSON object per line on stdout; **requires `--verbose`** | MEASURED |
| `--permission-mode acceptEdits` | file edits are auto-approved | MEASURED |
| `--allowedTools Bash,Read,Write,Edit,Glob,Grep` | these tools need no approval. `Bash` means any command as root in the container. | MEASURED |
| tools not in the list | need an approval that headless mode cannot give, so they are refused | UNVERIFIED (no denials seen in the measured run). The `init` event still *lists* every built-in tool. |
| `--dangerously-skip-permissions` | not needed, not used | - |

The kernel wraps each worker as `timeout -k 30 <cap_s> <cmd>` in its own process group
(`start_new_session=True`). `cap_s` is the time left to `MAX_HOURS`, as a safety net. The real deadline is enforced
by the control loop (SIGTERM to the group, then SIGKILL after `KILL_GRACE_S`), so the control file can move it.

## stream-json events seen (MEASURED)

| `type` / `subtype` | Content |
|---|---|
| `system/init` | model, `permissionMode`, `claude_code_version`, `apiKeySource`, tool list |
| `assistant` | model output, including `tool_use` blocks |
| `user` | tool results |
| `system/thinking_tokens` | thinking token counts |
| `system/task_started`, `system/task_notification` | background tasks |
| `tool_progress` | progress of a long tool call |
| `rate_limit_event` | `{"type":"rate_limit_event","rate_limit_info":{"status":"allowed_warning","rateLimitType":"seven_day","utilization":0.88,...}}` |
| `result` | final event: `subtype`, `num_turns`, `duration_ms`, `is_error` |

`scripts/stream_summary.py <log>...` prints model, permission mode, tool calls by tool, background tasks, the latest
rate-limit status and the final result, **without any message text**.

## Usage limits

All workers draw on **one subscription's** limits.

| Measured | Value |
|---|---|
| seven-day `utilization` seen by all 5 Opus agents | 0.88, then 0.89, then 0.90 over the first ~20 min |
| implied burn | about 5 to 6 points of the weekly window per hour for 5 agents (upper bound; the subscription may have been used elsewhere at the same time) |

At that rate a 5-agent station spends a weekly window in well under a day. Watch `rate_limit_event` in the logs, and
tell workers in the brief to stop on a usage refusal.

## Several instances

| Practice | Detail | Tag |
|---|---|---|
| one process per worker, staggered | `WORKER_STAGGER_S = 20` | MEASURED design |
| one log per worker | `out/logs/<NAME>.log` (stdout and stderr) | - |
| one folder per worker | `agents/<NAME>/`: `BRIEF.md`, `INBOX.md`, `STATUS.txt`, `STOP`, `REPORT.md`, `LESSONS.md` | MEASURED design |
| disjoint slices of work | the measured run split by item size band | MEASURED design |
| CPU budget in the brief | "at most one heavy process of your own at a time" | MEASURED design (docs/08) |
| client cost | each `claude` process: about 2.5 to 3% of one core, about 290 MB RSS | MEASURED |
| tool calls after ~20 min | 72 to 109 per worker, **all `Bash`**, about 40 background tasks each | MEASURED |
| sub-agents and background tasks | run inside the worker's process tree, on the same 4 vCPUs | MEASURED |

## Control-file conventions the brief must state

| File | Writer | Reader | Meaning |
|---|---|---|---|
| `agents/<N>/BRIEF.md` | station | worker, you | the prompt, saved |
| `agents/<N>/INBOX.md` | station (from control `messages`) | worker, at every batch boundary | appended `## <date> UTC - message <id>` blocks; newest last |
| `agents/<N>/STOP` | station (soft stop, `stop_all`) | worker | start nothing new, finish or release the item in flight, write REPORT.md, end |
| `agents/<N>/STATUS.txt` | worker | station (`status.json`) | one line, overwritten at every batch boundary |
| `agents/<N>/REPORT.md`, `LESSONS.md` | worker | you (results) | final report; lessons with evidence |

Workers see these files only when they look, so a message takes effect at the next batch boundary (minutes).

## Exit codes

| rc | Meaning |
|---|---|
| 0 | the worker finished its brief (or obeyed STOP) |
| 124 | `timeout` killed it at the `MAX_HOURS` cap |
| -15 / 143 | SIGTERM from the deadline kill |
| -9 / 137 | SIGKILL after `KILL_GRACE_S` |
