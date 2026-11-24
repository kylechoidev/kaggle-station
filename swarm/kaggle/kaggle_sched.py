#!/usr/bin/env python3
"""swarm/kaggle/kaggle_sched.py - keep up to N worker sessions per Kaggle account running (cron every 3-5 min on the hub).

Config: $SWARM_ROOT/kaggle/sched.json (see swarm/kaggle/sched.example.json). State: kaggle/state.json, log: kaggle/sched.log.
Per pass, per enabled account (Kaggle CLI run with HOME=<account home>, so each account uses its own login):
  1. `kernels list --mine`: count RUNNING/QUEUED kernels that are NOT ours (shared accounts: other projects first);
     the owner column is checked, because a CLI that falls back to another login lists another account's kernels
  2. `kernels status` of each of our slots (<slug_prefix>-1..N)
  3. stale-slot watchdog: a slot RUNNING/QUEUED whose relay status.json is older than stale_min (or missing that long
     after the push) is stale: alert; with "stale_action": "delete" a second stale pass deletes the kernel (frees the
     slot; the run's output is lost)
  4. launch free slots (status not RUNNING/QUEUED) while ours + others < cap (Kaggle's batch CPU cap is 5 per account,
     MEASURED 2026-11-23); state is saved right after each push
Stop semantics: kaggle/STOP_ALL containing
  "pause" -> launch nothing; running sessions continue to their deadline
  "yield" -> launch nothing AND write STOP_ALL into every slot's relay inbox: sessions finish their current item,
             release it and exit within a few minutes (use it to hand the account's slots to another project)
Remove the file to resume. --dry-run prints what it would do.
"""
import argparse, datetime as dt, fcntl, json, os, re, shutil, subprocess, sys, time

ROOT = os.path.abspath(os.environ.get('SWARM_ROOT', '.'))
K = os.path.join(ROOT, 'kaggle')
HERE = os.path.dirname(os.path.abspath(__file__))
DRY = False


def now():
    return dt.datetime.now(dt.timezone.utc)


def log(msg):
    line = '%s %s' % (now().strftime('%F %H:%M:%SZ'), msg)
    print(line, flush=True)
    with open(os.path.join(K, 'sched.log'), 'a') as f:
        f.write(line + '\n')


def load(p, d):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return d


def save(p, v):
    with open(p + '.tmp', 'w') as f:
        json.dump(v, f, indent=1)
    os.replace(p + '.tmp', p)


def kg(c, acc, args, timeout=300):
    e = {k: v for k, v in os.environ.items() if not k.startswith('KAGGLE_')}
    e['HOME'] = os.path.expanduser(acc['home'])
    r = subprocess.run([c.get('kaggle_cli', 'kaggle')] + args, env=e, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


def kstatus(c, acc, slug):
    rc, out = kg(c, acc, ['kernels', 'status', '%s/%s' % (acc['user'], slug)])
    m = re.search(r'(?:KernelWorkerStatus\.)?\b(RUNNING|QUEUED|COMPLETE|ERROR|CANCEL\w*)\b', out, re.I)
    return m.group(1).upper() if m else ('NONE' if '404' in out or 'not found' in out.lower() else 'UNKNOWN')


def others_busy(c, acc, ours):
    """RUNNING/QUEUED kernels of this account that are not ours. `kernels list --mine --csv` (CLI 2.x) has no status
    column (ref,title,author,lastRunTime,totalVotes), so kernels run in the last 13 h are asked one by one."""
    rc, out = kg(c, acc, ['kernels', 'list', '--mine', '--csv', '--page-size', '100', '--sort-by', 'dateRun'])
    busy, wrong_owner = 0, False
    for line in out.splitlines()[1:]:
        f = line.split(',')
        if not f or '/' not in f[0]:
            continue                       # (OBSERVED) odd lines without owner/slug: skip, never crash the pass
        owner, slug = f[0].split('/', 1)
        if owner.lower() != acc['user'].lower():
            wrong_owner = True
        if slug in ours:
            continue
        m = re.search(r'(\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d)', line)
        if m:
            t = dt.datetime.fromisoformat(m.group(1).replace(' ', 'T')).replace(tzinfo=dt.timezone.utc)
            if (now() - t).total_seconds() > 13 * 3600:
                continue
        if kstatus(c, acc, slug) in ('RUNNING', 'QUEUED'):
            busy += 1
    return busy, wrong_owner


def relay_dir(c, sub):
    return os.path.join(os.path.expanduser(c['relay']['root']), sub) if c.get('relay') else None


def render(c, acc, n, slug, sub):
    d = os.path.join(K, 'push', '%s-%d' % (acc['user'], n))
    shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    agent = '%s%d' % (acc.get('agent_prefix', 'K'), n)
    cfg = dict(agent=agent, provider=c['provider'], adapter=c['adapter'], worker_args=c.get('worker_args', []),
               run_hours=c.get('run_hours', 11.5), keys=c.get('keys', {}), relay_sub=sub,
               relay=dict(c['relay'], root=c['relay']['remote_root']) if c.get('relay') else None)
    with open(os.path.join(HERE, 'swarm_kernel.py')) as f:
        src = f.read()
    src = re.sub(r'^CONFIG = \{.*\}$', 'CONFIG = ' + json.dumps(cfg), src, count=1, flags=re.M)
    with open(os.path.join(d, 'swarm_kernel.py'), 'w') as f:
        f.write(src)
    meta = {'id': '%s/%s' % (acc['user'], slug), 'title': slug, 'code_file': 'swarm_kernel.py', 'language': 'python',
            'kernel_type': 'script', 'is_private': True, 'enable_gpu': False, 'enable_tpu': False,
            'enable_internet': True, 'dataset_sources': [x.format(user=acc['user']) for x in c['datasets']],
            'competition_sources': [], 'kernel_sources': [], 'model_sources': []}
    save(os.path.join(d, 'kernel-metadata.json'), meta)
    return d, agent


def main():
    global DRY
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    DRY = a.dry_run
    os.makedirs(K, exist_ok=True)
    lk = open(os.path.join(K, '.sched.lock'), 'w')
    try:
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print('another pass is running'); return
    c = load(os.path.join(K, 'sched.json'), None)
    if not c:
        sys.exit('no %s (copy swarm/kaggle/sched.example.json)' % os.path.join(K, 'sched.json'))
    st = load(os.path.join(K, 'state.json'), {'slots': {}})
    sf = os.path.join(K, 'STOP_ALL')
    mode = (open(sf).read().split() or ['pause'])[0].lower() if os.path.exists(sf) else None
    for acc in c['accounts']:
        if not acc.get('enabled', True):
            continue
        cap = int(acc.get('slots', 5))
        slugs = ['%s-%d' % (c.get('slug_prefix', 'swarm-worker'), n) for n in range(1, cap + 1)]
        others, wrong = others_busy(c, acc, set(slugs))
        if wrong:
            log('%s: kernels list shows another owner: wrong Kaggle login for this HOME; skipping' % acc['user']); continue
        ours = 0
        free = []
        for n, slug in enumerate(slugs, 1):
            key = '%s-%d' % (acc['user'], n)
            sub = '%s-%s-%d' % (c.get('relay_prefix', 'swarm'), acc['user'], n)
            s = st['slots'].setdefault(key, {})
            k = kstatus(c, acc, slug)
            if k != s.get('status'):
                log('%s: %s -> %s' % (key, s.get('status'), k))
            s['status'] = k
            rd = relay_dir(c, sub)
            if k in ('RUNNING', 'QUEUED'):
                ours += 1
                if mode == 'yield' and rd:
                    os.makedirs(os.path.join(rd, 'inbox'), exist_ok=True)
                    if not DRY:
                        open(os.path.join(rd, 'inbox', 'STOP_ALL'), 'w').write('yield\n')
                if rd and c.get('stale_min'):
                    p = os.path.join(rd, 'outbox', 'status.json')
                    last = os.path.getmtime(p) if os.path.exists(p) else s.get('pushed_t', time.time())
                    if time.time() - last > 60 * c['stale_min']:
                        s['stale'] = s.get('stale', 0) + 1
                        log('%s: STALE (no relay status for %.0f min, pass %d)' % (key, (time.time() - last) / 60, s['stale']))
                        if c.get('stale_action') == 'delete' and s['stale'] >= 2 and not DRY:
                            rc, out = kg(c, acc, ['kernels', 'delete', '%s/%s' % (acc['user'], slug), '-y'])
                            log('%s: deleted stale kernel rc %d %s' % (key, rc, out.strip()[-120:]))
                    else:
                        s['stale'] = 0
            else:
                free.append((n, slug, sub, key))
        for n, slug, sub, key in free:
            if mode or ours + others >= cap:
                break
            d, agent = render(c, acc, n, slug, sub)
            rd = relay_dir(c, sub)
            if rd and not DRY:
                for x in ('inbox', 'outbox'):
                    shutil.rmtree(os.path.join(rd, x), ignore_errors=True); os.makedirs(os.path.join(rd, x))
            if DRY:
                log('%s: DRY would push %s as %s/%s (agent %s)' % (key, d, acc['user'], slug, agent)); ours += 1; continue
            rc, out = kg(c, acc, ['kernels', 'push', '-p', d])
            s = st['slots'][key]
            if rc == 0 and 'successfully pushed' in out.lower():
                s.update(status='PUSHED', pushed=now().isoformat(timespec='seconds'), pushed_t=time.time(), agent=agent, stale=0)
                ours += 1
                log('%s: pushed %s/%s (agent %s)' % (key, acc['user'], slug, agent))
            else:
                log('%s: push FAILED: %s' % (key, out.strip()[-200:]))
                if 'maximum' in out.lower():
                    break                   # account at its session cap (other kernels count too)
            save(os.path.join(K, 'state.json'), st)   # right after each push (OBSERVED: a crash re-pushed an account)
    st['t'] = now().isoformat(timespec='seconds'); st['mode'] = mode
    save(os.path.join(K, 'state.json'), st)


if __name__ == '__main__':
    main()
