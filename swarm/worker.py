#!/usr/bin/env python3
"""swarm/worker.py - one free-model worker: take item -> ask the model -> verify -> feedback rounds -> submit or give up.

The workload lives in an ADAPTER (a Python file with a class `Adapter`, see swarm/adapters/). The worker owns the model
calls, the rounds, the stop flags and the status file. Docs: docs/12_free_model_swarm.md.

  phase A (practice): adapter.practice_items() -> solve offline until the first pass; nothing is submitted.
  phase B (live):     adapter.get_item() -> solve -> adapter.submit() on a pass, else adapter.give_up(best, reason).
  Items still held at exit (SIGTERM, error) are handed to adapter.release().

Stops (checked between items): <work>/agents/<AGENT>/STOP, <work>/flags/<NAME> for every name in --flags
(default STOP_ALL DAILY_CAP_STOP VERIFIER_STALE REMOTE_HALT), --max-items, --deadline-min.
Model-side stops: LLM_DEAL_ENDED (HTTP 401/402/403/404), LLM_COST (usage.cost > 0), LLM_DOWN (8 failures in a row).
Status: <work>/agents/<AGENT>/status.json (every 20 s and at exit), events.log, answers.jsonl (no prompts stored).

Usage:
  SWARM_ROOT=. python3 -I swarm/worker.py --provider NAME --providers swarm/providers.json \
      --adapter swarm/adapters/pytests_example.py --agent W1 [--phase AB] [--rounds 4] [--threads 1]
Keys: providers.json holds the PATH of a key file per provider; the key is read at call time and never printed.
"""
import argparse, collections, datetime as dt, hashlib, importlib.util, json, os, re, signal, sys, threading, time
import traceback, urllib.error, urllib.request

ROOT = os.path.abspath(os.environ.get('SWARM_ROOT', '.'))
STATE = dict(phase='init', started=time.time(), answers=0, passes=0, submits=0, giveups=0, items=0, errors=0,
             stop=None, llm_s=0.0, llm_n=0, item_s=0.0, provider=None, llm_last_http=None, ratelimit=None,
             last=collections.deque(maxlen=12))
HELD = {}            # item key -> item (claimed, not yet submitted / given up)
LOCK = threading.Lock()
FAILS = [0]
A = P = AD = None
WDIR = None


def now():
    return dt.datetime.now(dt.timezone.utc)


def log(msg):
    line = '%s %s' % (now().strftime('%H:%M:%S'), msg)
    print(line, flush=True)
    with LOCK:
        STATE['last'].append(line[:200])
        with open(os.path.join(WDIR, 'events.log'), 'a') as f:
            f.write(line + '\n')


def jsonl(name, rec):
    with LOCK, open(os.path.join(WDIR, name), 'a') as f:
        f.write(json.dumps(rec, default=str) + '\n')


def write_status(final=False):
    s = {k: (list(v) if isinstance(v, collections.deque) else v) for k, v in STATE.items()}
    s.update(t=now().isoformat(timespec='seconds'), agent=A.agent, uptime_min=round((time.time() - STATE['started']) / 60, 1),
             s_per_answer=round(STATE['llm_s'] / STATE['llm_n'], 1) if STATE['llm_n'] else None,
             s_per_item=round(STATE['item_s'] / STATE['items'], 1) if STATE['items'] else None,
             held=list(HELD), stop_reason=stop_reason(), final=final)
    p = os.path.join(WDIR, 'status.json')
    with open(p + '.tmp', 'w') as f:
        json.dump(s, f, indent=1, default=str)
    os.replace(p + '.tmp', p)


def stop_reason():
    if STATE['stop']:
        return STATE['stop']
    if os.path.exists(os.path.join(WDIR, 'STOP')):
        return 'STOP'
    for name in A.flags:
        if os.path.exists(os.path.join(ROOT, 'work', 'flags', name)):
            return {'DAILY_CAP_STOP': 'CAPACITY', 'VERIFIER_STALE': 'KIT_STALE'}.get(name, name)
    if A.deadline_min and time.time() - STATE['started'] > A.deadline_min * 60:
        return 'deadline'
    if A.max_items and STATE['items'] >= A.max_items:
        return 'max_items'
    return None


# ------------------------------------------------------------------ model
def llm(messages, temperature, max_tokens):
    body = dict(model=P['model'], messages=messages, temperature=temperature, max_tokens=max_tokens, stream=False)
    body.update(P.get('extra') or {})
    hdr = {'Content-Type': 'application/json', 'User-Agent': 'swarm-worker/1'}
    if P.get('key'):
        with open(os.path.expanduser(P['key'])) as f:
            hdr['Authorization'] = 'Bearer ' + f.read().strip()
    req = urllib.request.Request(P['url'].rstrip('/') + '/chat/completions', data=json.dumps(body).encode(),
                                 headers=hdr, method='POST')
    t0 = time.time()
    for tr in range(6):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                d = json.load(r)
                STATE['llm_last_http'] = r.status
                rl = {k.lower(): v for k, v in r.headers.items() if 'ratelimit' in k.lower()}
                if rl:
                    STATE['ratelimit'] = rl
            break
        except urllib.error.HTTPError as e:
            STATE['llm_last_http'] = e.code
            if e.code in (401, 402, 403, 404):
                STATE['stop'] = STATE['stop'] or 'LLM_DEAL_ENDED'
                log('LLM HTTP %d (model %s): deal ended? stopping' % (e.code, P['model']))
                raise
            if e.code in (429, 500, 502, 503, 504) and tr < 5:
                time.sleep(10 * (tr + 1)); continue
            raise
    el = time.time() - t0
    us = d.get('usage') or {}
    try:
        cost = float(us.get('cost') or us.get('total_cost') or 0)
    except (TypeError, ValueError):
        cost = 0
    if cost > 0:
        STATE['stop'] = STATE['stop'] or 'LLM_COST'
        log('LLM reported cost %s: no longer free; stopping' % cost)
    with LOCK:
        STATE['llm_s'] += el; STATE['llm_n'] += 1
    ch = (d.get('choices') or [{}])[0]
    return (ch.get('message') or {}).get('content') or '', dict(secs=round(el, 1), finish=ch.get('finish_reason'),
                                                               completion_tokens=us.get('completion_tokens'))


def default_extract(reply):
    m = re.findall(r'```[a-zA-Z0-9_+-]*\n(.*?)```', reply, flags=re.S)
    return (max(m, key=len) if m else reply).strip() + '\n'


# ------------------------------------------------------------------ solving
def solve(item, practice):
    """-> (passed, best_candidate, best_feedback, rounds)"""
    history, best, seen = [], None, set()
    temps = [0.2, 0.2, 0.7, 0.4] + [0.5] * 20
    for rnd in range(A.rounds):
        if stop_reason() and STATE['stop']:
            break
        msgs = AD.build_prompt(item, history)
        try:
            reply, meta = llm(msgs, temps[rnd], A.max_tokens)
        except Exception as e:
            STATE['errors'] += 1; FAILS[0] += 1
            log('LLM error on %s round %d: %s' % (AD.key(item), rnd + 1, str(e)[:200]))
            if FAILS[0] >= 8:
                STATE['stop'] = STATE['stop'] or 'LLM_DOWN'
            if STATE['stop']:
                break
            time.sleep(10); continue
        FAILS[0] = 0
        STATE['answers'] += 1
        cand = (getattr(AD, 'extract', None) or default_extract)(reply)
        h = hashlib.sha1(cand.encode()).hexdigest()
        if h in seen:
            ok, fb, score = False, 'duplicate of an earlier answer: try a different approach', None
        else:
            seen.add(h)
            try:
                ok, fb, score = AD.verify(item, cand)
            except Exception as e:
                ok, fb, score = False, 'verifier error: %s' % e, None
        jsonl('answers.jsonl', dict(t=now().isoformat(timespec='seconds'), item=AD.key(item), round=rnd + 1,
                                    practice=practice, ok=ok, score=score, feedback=str(fb)[:300], **meta))
        if best is None or ok or (score is not None and (best[2] is None or score < best[2])):
            best = (cand, fb, score)
        if ok:
            return True, cand, fb, rnd + 1
        history.append((cand, fb))
    return False, best[0] if best else None, best[1] if best else 'no answer', A.rounds


def phase_a():
    STATE['phase'] = 'A'
    items = list(AD.practice_items(A.practice_n)) if hasattr(AD, 'practice_items') else []
    if not items:
        log('phase A: adapter has no practice items; skipping the gate')
        return True
    res = collections.Counter()
    for it in items:
        if stop_reason():
            return False
        t0 = time.time()
        ok, cand, fb, rounds = solve(it, True)
        STATE['items'] += 1; STATE['item_s'] += time.time() - t0
        res['pass' if ok else 'fail'] += 1
        log('phase A %s: %s in %d rounds, %.0f s' % (AD.key(it), 'PASS' if ok else 'no pass', rounds, time.time() - t0))
        if ok:
            STATE['passes'] += 1
            log('phase A gate passed: %s' % dict(res))
            return True
    STATE['stop'] = STATE['stop'] or 'PHASE_A_EXHAUSTED'
    log('phase A gate NOT passed: %s' % dict(res))
    return False


def worker_thread(wid):
    while not stop_reason():
        try:
            it = AD.get_item()
        except Exception as e:
            log('w%d get_item error: %s' % (wid, e)); STATE['errors'] += 1; time.sleep(30); continue
        if it is None:
            log('w%d: no more items' % wid); return
        k = AD.key(it)
        with LOCK:
            HELD[k] = it
        t0 = time.time()
        try:
            ok, cand, fb, rounds = solve(it, False)
            STATE['items'] += 1; STATE['item_s'] += time.time() - t0
            if ok:
                STATE['passes'] += 1
                sok, info = AD.submit(it, cand)
                STATE['submits' if sok else 'giveups'] += 1
                if not sok:
                    AD.give_up(it, cand, 'passed locally but submit failed: %s' % info)
                log('w%d %s PASS in %d rounds, submit %s %s' % (wid, k, rounds, 'ok' if sok else 'FAILED', str(info)[:120]))
            else:
                why = 'stopped (%s) before a pass' % STATE['stop'] if STATE['stop'] else 'no pass in %d rounds; last feedback: %s' % (rounds, str(fb)[:160])
                AD.give_up(it, cand, why)
                STATE['giveups'] += 1
                log('w%d %s no pass in %d rounds (%.0f s)' % (wid, k, rounds, time.time() - t0))
        except Exception as e:
            STATE['errors'] += 1
            log('w%d %s error: %s' % (wid, k, e)); traceback.print_exc()
            try:
                AD.release(it)
            except Exception:
                pass
        finally:
            with LOCK:
                HELD.pop(k, None)


def release_all(why):
    for k, it in list(HELD.items()):
        try:
            AD.release(it); log('released %s (%s)' % (k, why))
        except Exception as e:
            log('release %s failed: %s' % (k, e))
        HELD.pop(k, None)


def on_term(sig, frm):
    log('signal %d: releasing held items' % sig)
    STATE['stop'] = STATE['stop'] or 'SIGTERM'
    release_all('signal')
    write_status(True)
    os._exit(0)


def load_adapter(path):
    spec = importlib.util.spec_from_file_location('swarm_adapter', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Adapter(A, log)


def main():
    global A, P, AD, WDIR
    ap = argparse.ArgumentParser()
    ap.add_argument('--provider', required=True)
    ap.add_argument('--providers', default=os.environ.get('SWARM_PROVIDERS') or os.path.join(ROOT, 'swarm', 'providers.json'))
    ap.add_argument('--adapter', required=True, help='path of a Python file defining class Adapter')
    ap.add_argument('--adapter-arg', action='append', default=[], help='KEY=VALUE passed to the adapter (repeatable)')
    ap.add_argument('--agent', required=True)
    ap.add_argument('--phase', default='AB')
    ap.add_argument('--rounds', type=int, default=4)
    ap.add_argument('--threads', type=int, default=1)
    ap.add_argument('--practice-n', type=int, default=5)
    ap.add_argument('--max-tokens', type=int, default=4096)
    ap.add_argument('--max-items', type=int, default=0)
    ap.add_argument('--deadline-min', type=float, default=0)
    ap.add_argument('--flags', nargs='*', default=['STOP_ALL', 'DAILY_CAP_STOP', 'VERIFIER_STALE', 'REMOTE_HALT'])
    A = ap.parse_args()
    A.adapter_args = dict(x.split('=', 1) for x in A.adapter_arg)
    with open(A.providers) as f:
        provs = json.load(f)
    if A.provider not in provs or not isinstance(provs[A.provider], dict):
        sys.exit('unknown provider %s in %s' % (A.provider, A.providers))
    P = provs[A.provider]
    STATE['provider'] = A.provider
    WDIR = os.path.join(ROOT, 'work', 'agents', A.agent)
    os.makedirs(WDIR, exist_ok=True)
    os.makedirs(os.path.join(ROOT, 'work', 'flags'), exist_ok=True)
    AD = load_adapter(A.adapter)
    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)

    def status_loop():
        while True:
            try:
                write_status()
            except Exception as e:
                print('status error', e, flush=True)
            time.sleep(20)
    threading.Thread(target=status_loop, daemon=True).start()
    log('worker %s start: provider %s (model %s), adapter %s, phase %s' % (A.agent, A.provider, P['model'],
                                                                           os.path.basename(A.adapter), A.phase))
    try:
        if 'A' in A.phase and not phase_a():
            return 3
        if 'B' in A.phase and not stop_reason():
            STATE['phase'] = 'B'
            ts = [threading.Thread(target=worker_thread, args=(i,)) for i in range(A.threads)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
    finally:
        release_all('exit')
        STATE['phase'] = 'done'
        write_status(True)
        log('worker done: %s' % {k: STATE[k] for k in ('answers', 'passes', 'submits', 'giveups', 'errors', 'stop')})
    return 0


if __name__ == '__main__':
    sys.exit(main())
