#!/usr/bin/env python3
"""swarm/hub/host.py - the per-host half of the hub (no model, no credits). Runs on every host.

All paths are relative to $SWARM_ROOT (default: current directory). Config: $SWARM_ROOT/hub/config.json (master on
the hub host, copied to the others by hub/tick.py; see swarm/hub/config.example.json).

  host.py tick [--may-start a,b] [--no-update]   one pass for THIS host; prints a JSON report and saves hub/hosts/<host>.json
      1. self-update of the verifier/toolchain (config "self_update", at most every update_every_min)
      2. ledger export: files matching config ledger.export_glob -> hub/outgoing/results/<name>.json (+host, +t)
      3. singletons assigned to this host: start daemons that are down (only those in --may-start), place a "hub:"
         STOP on daemons assigned elsewhere; periodic jobs when due; cron-type ones are only reported
      4. worker watchdog for workers with "watch": true on this host (restartable vs never-restart stop reasons,
         daily cap, provider switch)
  host.py workers                     workers running here (agent, pid, provider)
  host.py start <AGENT> [--provider P] start one registered worker now
Workers are found through /proc/*/cmdline (basename worker.py + --agent NAME): no pkill/pgrep self-matching.
"""
import argparse, datetime as dt, fcntl, glob, json, os, shutil, socket, subprocess, sys, time

ROOT = os.path.abspath(os.environ.get('SWARM_ROOT', '.'))
HUB = os.path.join(ROOT, 'hub')
W = os.path.join(ROOT, 'work')
CONF = os.environ.get('SWARM_HUB_CONF', os.path.join(HUB, 'config.json'))
RESTARTABLE = {None, '', 'KIT_STALE', 'LLM_DOWN', 'PHASE_A_EXHAUSTED', 'deadline', 'max_items', 'crash', 'reboot', 'switch'}
NEVER = {'STOP', 'STOP_ALL', 'CAPACITY', 'REMOTE_HALT', 'LLM_DEAL_ENDED', 'LLM_COST'}
FLAGS = ('STOP_ALL', 'DAILY_CAP_STOP', 'VERIFIER_STALE', 'REMOTE_HALT')


def now():
    return dt.datetime.now(dt.timezone.utc)


def iso(t=None):
    return (t or now()).isoformat(timespec='seconds')


def load(p, d=None):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return d


def save(p, v):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + '.tmp', 'w') as f:
        json.dump(v, f, indent=1, default=str)
    os.replace(p + '.tmp', p)


def conf():
    return load(CONF, {}) or {}


def me(c=None):
    c = c or conf()
    hn = socket.gethostname()
    for name, h in (c.get('hosts') or {}).items():
        if h.get('hostname') == hn:
            return name
    return os.environ.get('SWARM_HOST') or hn


def log(msg, host=None):
    os.makedirs(os.path.join(HUB, 'log'), exist_ok=True)
    with open(os.path.join(HUB, 'log', 'host_%s.log' % (host or me())), 'a') as f:
        f.write('%s %s\n' % (now().strftime('%F %H:%M:%SZ'), msg))


def alert(msg, host=None):
    os.makedirs(os.path.join(HUB, 'alerts'), exist_ok=True)
    with open(os.path.join(HUB, 'alerts', '%s.txt' % (host or me())), 'a') as f:
        f.write('%s [%s] %s\n' % (iso(), host or me(), msg))
    log('ALERT ' + msg, host)


def py(c):
    return c.get('python') or sys.executable


def env(c):
    e = dict(os.environ, SWARM_ROOT=ROOT)
    e.update({k: str(v) for k, v in (c.get('env') or {}).items()})
    return e


# ------------------------------------------------------------------ processes
def procs():
    out = []
    for p in glob.glob('/proc/[0-9]*/cmdline'):
        try:
            with open(p, 'rb') as f:
                a = [x.decode('utf-8', 'replace') for x in f.read().split(b'\0') if x]
        except Exception:
            continue
        if a:
            out.append((int(p.split('/')[2]), a))
    return out


def workers_running():
    res = {}
    for pid, a in procs():
        if any(os.path.basename(x) == 'worker.py' for x in a) and '--agent' in a:
            ag = a[a.index('--agent') + 1]
            res[ag] = dict(pid=pid, provider=a[a.index('--provider') + 1] if '--provider' in a else '?')
    return res


def running(match):
    hits = []
    for pid, a in procs():
        if pid == os.getpid():
            continue
        names = set(a) | {os.path.basename(x) for x in a}
        if all(m in names for m in match):
            hits.append(pid)
    return hits


def spawn(cmd, logfile, c):
    os.makedirs(os.path.dirname(logfile), exist_ok=True)
    lf = open(logfile, 'a')
    p = subprocess.Popen(cmd, cwd=ROOT, env=env(c), stdout=lf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         start_new_session=True)
    return p.pid


# ------------------------------------------------------------------ workers
def worker_cmd(c, w, provider):
    cmd = [py(c), '-I', os.path.join(ROOT, 'swarm', 'worker.py'), '--provider', provider, '--agent', w['agent'],
           '--adapter', w['adapter']]
    if c.get('providers_file'):
        cmd += ['--providers', os.path.join(ROOT, c['providers_file'])]
    return cmd + list(w.get('args', []))


def start_worker(c, w, provider=None):
    prov = provider or w.get('provider') or c.get('default_provider')
    pid = spawn(worker_cmd(c, w, prov), os.path.join(W, 'agents', w['agent'], 'worker.log'), c)
    log('started worker %s provider %s pid %d' % (w['agent'], prov, pid))
    return pid


def flags_set(agent):
    out = [os.path.join('work', 'flags', f) for f in FLAGS if os.path.exists(os.path.join(W, 'flags', f))]
    if os.path.exists(os.path.join(W, 'agents', agent, 'STOP')):
        out.append(os.path.join('work', 'agents', agent, 'STOP'))
    return out


def wstatus(agent):
    s = load(os.path.join(W, 'agents', agent, 'status.json'), {}) or {}
    keep = ('t', 'phase', 'uptime_min', 'answers', 'passes', 'submits', 'giveups', 'items', 'errors', 'stop',
            's_per_answer', 's_per_item', 'provider', 'llm_last_http', 'ratelimit', 'final')
    return {k: s.get(k) for k in keep if k in s}


def watch(c, host, rep):
    run = workers_running()
    sa = load(os.path.join(HUB, 'watch_state.json'), {}) or {}
    for w in c.get('workers', []):
        if w.get('host') != host:
            continue
        ag = w['agent']
        want = w.get('provider') or c.get('default_provider')
        st = sa.setdefault(ag, {})
        info = dict(agent=ag, watch=bool(w.get('watch')), want_provider=want, status=wstatus(ag), flags=flags_set(ag))
        stopf = os.path.join(W, 'agents', ag, 'STOP')
        if ag in run:
            info.update(running=True, pid=run[ag]['pid'], provider=run[ag]['provider'])
            if w.get('watch') and run[ag]['provider'] != want and not os.path.exists(stopf):
                os.makedirs(os.path.dirname(stopf), exist_ok=True)
                with open(stopf, 'w') as f:
                    f.write('hub: provider switch %s -> %s\n' % (run[ag]['provider'], want))
                st['switch_to'] = want
                log('%s: provider switch %s -> %s (STOP placed)' % (ag, run[ag]['provider'], want))
            rep['workers'].append(info); continue
        info['running'] = False
        switched = False
        if os.path.exists(stopf) and st.get('switch_to'):
            with open(stopf) as f:
                if f.read().startswith('hub:'):
                    os.remove(stopf); st.pop('switch_to', None); st['last_restart'] = 0; switched = True
        if not w.get('watch'):
            rep['workers'].append(info); continue
        s = info['status']
        why = s.get('stop')
        if not s.get('final') and why is None:
            why = 'crash'
        if why == 'SIGTERM':
            try:
                boot = time.time() - float(open('/proc/uptime').read().split()[0])
                if boot > dt.datetime.fromisoformat(s.get('t')).timestamp():
                    why = 'reboot'
            except Exception:
                pass
        if switched:
            why = 'switch'
        fl = flags_set(ag)
        today = now().strftime('%F')
        if st.get('day') != today:
            st['day'], st['n'] = today, 0
        gap = 1800 if why in ('LLM_DOWN', 'PHASE_A_EXHAUSTED') else 600
        if fl:
            info['decision'] = 'held: ' + ','.join(fl)
        elif why in NEVER or why not in RESTARTABLE:
            info['decision'] = 'not restarted: stop reason %s' % why
            if st.get('alerted') != why:
                alert('worker %s stopped with %s; needs a human or the coordinator' % (ag, why), host); st['alerted'] = why
        elif time.time() - st.get('last_restart', 0) < gap:
            info['decision'] = 'backoff (%d s left)' % (gap - (time.time() - st.get('last_restart', 0)))
        elif st['n'] >= int(c.get('max_restarts_per_day', 12)):
            info['decision'] = 'daily restart cap reached'
            if st.get('alerted') != 'cap':
                alert('worker %s hit the daily restart cap' % ag, host); st['alerted'] = 'cap'
        else:
            info['pid'] = start_worker(c, w, want)
            info['decision'] = 'restarted (previous stop: %s)' % why
            st.update(last_restart=time.time(), n=st['n'] + 1, alerted=None)
        rep['workers'].append(info)
    reg = {w['agent'] for w in c.get('workers', []) if w.get('host') == host}
    for ag, r in run.items():
        if ag not in reg:
            rep['workers'].append(dict(agent=ag, running=True, registered=False, status=wstatus(ag), **r))
    save(os.path.join(HUB, 'watch_state.json'), sa)


# ------------------------------------------------------------------ singletons
def singletons(c, host, may_start, rep):
    for name, s in (c.get('singletons') or {}).items():
        kind = s.get('type', 'daemon')
        mine = s.get('host') == host
        r = dict(name=name, type=kind, assigned=s.get('host'))
        cmd = [x.replace('{python}', py(c)).replace('{root}', ROOT) for x in s.get('cmd', [])]
        lf = os.path.join(ROOT, s.get('log', 'hub/log/%s.out' % name))
        if kind == 'daemon':
            pids = running(s['match'])
            r['pids'] = pids
            sf = os.path.join(ROOT, s['stopfile']) if s.get('stopfile') else None
            hub_stop = bool(sf and os.path.exists(sf) and open(sf).read().startswith('hub:'))
            if mine:
                if hub_stop and not pids:
                    os.remove(sf); log('%s: removed hub STOP (assigned here)' % name)
                if pids:
                    r['state'] = 'running'
                elif sf and os.path.exists(sf):
                    r['state'] = 'stopped by STOP file (human)'
                elif name not in may_start:
                    r['state'] = 'down; start not allowed this pass'
                else:
                    r['state'] = 'started pid %d' % spawn(cmd, lf, c); log('%s: %s' % (name, r['state']))
            elif pids:
                if sf:
                    if not os.path.exists(sf):
                        os.makedirs(os.path.dirname(sf), exist_ok=True)
                        with open(sf, 'w') as f:
                            f.write('hub: %s is assigned to %s\n' % (name, s.get('host')))
                    r['state'] = 'stopping (assigned elsewhere)'
                else:
                    for pid in pids:
                        os.kill(pid, 15)
                    r['state'] = 'killed (assigned elsewhere)'
                log('%s: running here but assigned to %s: %s' % (name, s.get('host'), r['state']))
            else:
                r['state'] = 'not here'
        elif kind == 'periodic' and mine:
            stamp = os.path.join(ROOT, s['stamp'])
            age = (time.time() - os.path.getmtime(stamp)) / 60 if os.path.exists(stamp) else 1e9
            r['age_min'] = round(age, 1)
            if age >= s.get('every_min', 15) and not running(s['match']):
                spawn(cmd, lf, c); r['state'] = 'started (age %.0f min)' % age
            else:
                r['state'] = 'fresh' if age < s.get('every_min', 15) else 'running'
        elif kind == 'cron':
            r['state'] = 'cron on %s (swarm/hub/guard.py %s)' % (s.get('host'), name)
        rep['singletons'].append(r)


# ------------------------------------------------------------------ ledger
def ledger_export(c, host):
    lc = c.get('ledger') or {}
    out = os.path.join(HUB, 'outgoing', 'results')
    os.makedirs(out, exist_ok=True)
    n = 0
    for p in glob.glob(os.path.join(ROOT, lc.get('export_glob', 'work/results/*.json'))):
        dst = os.path.join(out, os.path.basename(p))
        mt = os.path.getmtime(p)
        if os.path.exists(dst) and os.path.getmtime(dst) >= mt:
            continue
        rec = load(p)
        if not isinstance(rec, dict):
            continue
        rec.update(host=host, t=dt.datetime.fromtimestamp(mt, dt.timezone.utc).isoformat(timespec='seconds'))
        save(dst, rec); os.utime(dst, (mt, mt)); n += 1
    return n


# ------------------------------------------------------------------ main
def tick(a):
    c = conf()
    host = me(c)
    rep = dict(host=host, hostname=socket.gethostname(), t=iso(), workers=[], singletons=[], load=os.getloadavg(),
               flags=[f for f in FLAGS if os.path.exists(os.path.join(W, 'flags', f))])
    try:
        with open('/proc/meminfo') as f:
            rep['mem_avail_mb'] = int([l for l in f if l.startswith('MemAvailable')][0].split()[1]) // 1024
    except Exception:
        pass
    su = c.get('self_update')
    if su and not a.no_update:
        last = load(os.path.join(HUB, 'self_update_last.json'), {}) or {}
        stale = os.path.exists(os.path.join(W, 'flags', 'VERIFIER_STALE'))
        if time.time() - last.get('t', 0) >= 60 * su.get('every_min', 10) or stale:
            r = subprocess.run([py(c), '-I', os.path.join(ROOT, 'swarm', 'hub', 'self_update.py')], cwd=ROOT,
                               env=env(c), capture_output=True, text=True, timeout=3600)
            last = dict(t=time.time(), rc=r.returncode, out=(r.stdout + r.stderr).strip()[-500:])
            save(os.path.join(HUB, 'self_update_last.json'), last)
        rep['self_update'] = last
    rep['ledger_exported'] = ledger_export(c, host)
    singletons(c, host, set(filter(None, (a.may_start or '').split(','))), rep)
    watch(c, host, rep)
    save(os.path.join(HUB, 'hosts', '%s.json' % host), rep)
    print(json.dumps(rep, default=str))


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest='cmd', required=True)
    t = sp.add_parser('tick'); t.add_argument('--may-start', default=''); t.add_argument('--no-update', action='store_true')
    sp.add_parser('workers')
    s = sp.add_parser('start'); s.add_argument('agent'); s.add_argument('--provider')
    a = ap.parse_args()
    for d in ('', 'requests', 'requests_done', 'coord', 'alerts', 'hosts', 'log'):
        os.makedirs(os.path.join(HUB, d), exist_ok=True)
    os.makedirs(os.path.join(W, 'flags'), exist_ok=True)
    if a.cmd == 'tick':
        lock = open(os.path.join(HUB, '.host_tick.lock'), 'w')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print(json.dumps(dict(host=me(), busy=True))); return
        tick(a)
    elif a.cmd == 'workers':
        print(json.dumps(workers_running(), indent=1))
    else:
        c = conf()
        w = [x for x in c.get('workers', []) if x['agent'] == a.agent]
        if not w:
            sys.exit('not registered in %s: %s' % (CONF, a.agent))
        if a.agent in workers_running():
            sys.exit('%s is already running' % a.agent)
        print(start_worker(c, w[0], a.provider))


if __name__ == '__main__':
    main()
