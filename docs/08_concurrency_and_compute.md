# 08 - Concurrency and compute (measured)

## The machine

4 vCPUs (2 cores x 2 hyper-threads, Xeon @ 2.20 GHz, cgroup-capped at 4.0 CPUs), 30 GiB RAM (cgroup), no swap,
20 GB `/kaggle/working`. Details in docs/01.

## Who uses the CPU

The **model** runs on Anthropic's side. A Claude Code process in the container is a client: it streams tokens,
runs tool calls and keeps a transcript.

| Process | CPU | RAM | Tag |
|---|---|---|---|
| one `claude -p` worker (client only, excluding the tools it launches) | 15 to 19 CPU-seconds over ~11 min = about **2.5 to 3 % of one core** | ~280 to 300 MB RSS | MEASURED |
| five workers together | about 0.15 core | about 1.4 GB | MEASURED |
| the tools they run (here: a compiler under Wine, a Python checker, disassembly) | everything else | small | MEASURED |
| Wine overhead | kernel (`sy`) time ran at roughly half of user time (`/proc/stat`: user 93,860 vs system 46,956 jiffies since boot); `wineserver` alone ~18 % of a core at times | - | MEASURED |

So the number of agents is limited by **the work they launch**, not by the agents. Memory is not a constraint for
this kind of work (peak used RAM stayed far below 30 GiB, see table).

## Load while five agents worked (4 compile-and-check workers + this documentation agent)

Sampled every 3 minutes by a background loop (`/proc/loadavg`; CPU busy = non-idle share of all 4 CPUs over a
5-second window from `/proc/stat`; `free -m`). Each worker was told "at most one compile process of your own at a
time". The first rows are the start-up phase (agents reading docs before their first batch).

<!-- LOAD -->
| UTC | load 1/5/15 min | CPU busy % (5 s sample) | RAM used / available (MiB) |
|---|---|---|---|
| 15:00 | 0.70 / 0.81 / 0.45 | 8 | 1846 / 30252 |
| 15:03 | 1.03 / 0.80 / 0.50 | 53 | 2385 / 29711 |
| 15:06 | 2.24 / 1.48 / 0.82 | 30 | 2362 / 29735 |
| 15:09 | 2.99 / 2.08 / 1.17 | 64 | 2369 / 29729 |
| 15:12 | 2.38 / 2.23 / 1.39 | 28 | 2046 / 30052 |
| 15:15 | 1.84 / 2.26 / 1.56 | 5 | 2010 / 30088 |
| 15:18 | 2.31 / 2.15 / 1.63 | 46 | 2413 / 29685 |
| 15:20 | 2.18 / 2.14 / 1.71 | 50 | 2492 / 29606 |
| 15:23 | 2.46 / 2.33 / 1.87 | 98 | 3130 / 28968 |
| 15:26 | 5.08 / 3.47 / 2.38 | 95 | 2889 / 29209 |
| 15:29 | 4.25 / 3.82 / 2.71 | 23 | 1963 / 30135 |
| 15:32 | 1.99 / 3.00 / 2.60 | 3 | 1472 / 30626 |
| 15:35 | 1.56 / 2.39 / 2.43 | 2 | 1235 / 30863 |

Summary over 13 samples (15:00-15:35 UTC): CPU busy mean 39%, min 2%, max 98%; load1 mean 2.39, max 5.08; RAM used max 3130 MiB of 30 GiB.
<!-- /LOAD -->

A 60-second probe at ~15:09 UTC (one sample every 2 s) saw 2 to 6 compiler-related processes alive at once and
load1 between 2.3 and 3.0.

## Reading the numbers

- With one compile per worker, four workers kept the 4-vCPU session **busy about half the time on average,
  with bursts that saturate it** (see the summary above: peaks near 100 % busy and load1 above 4, i.e. short
  queueing). In the first 20 minutes, while agents were still reading and setting up, it averaged only about a
  third. Agents spend much of their wall-clock waiting for the model, so compile bursts mostly interleave.
  Four heavy agents per session is a reasonable default; a fifth light agent fit without trouble. Adding more
  heavy agents would deepen the bursts - measure first, and watch the subscription burn (05), which grows with
  the number of agents, not with CPU.
- Hyper-threads: 4 vCPUs are 2 physical cores. Two compiles on sibling threads run slower than on separate cores;
  expect ~2.5 to 3 x one-core throughput from 4 parallel compiles, not 4 x (general SMT behaviour, UNVERIFIED here - we
  did not run a compile benchmark because the workers needed the CPU).
- Agent sub-agents and background tasks run in the same container and compete for the same 4 vCPUs.

## Sizing advice

| Work per agent | Agents per CPU session |
|---|---|
| mostly thinking/editing, occasional short builds | 4 to 6 |
| one heavy single-threaded tool at a time (this run) | **4** (measured: ~1/2 busy on average, saturating bursts) + one light agent |
| parallel builds (`-j4`, multi-job checkers) | 1 to 2, or force `--jobs 1` per agent |

- Put the CPU budget into the brief ("at most one heavy process of your own at a time", `--jobs 1`).
- Give agents disjoint work slices; a shared queue needs an atomic claim step.
- Need more throughput? Run more **sessions** (per-account cap applies, 01), each with its own gate, rather
  than more agents per session. All sessions draw on one Claude subscription (05).
- Measure your own workload: add `nohup bash <path>/load_sampler.sh /kaggle/working/out/load.tsv 180 >/dev/null 2>&1 &`
  to `SETUP_SHELL` (ship the script in the kit). It reads `/proc/loadavg`, `/proc/stat` and `free`, and costs nothing.
