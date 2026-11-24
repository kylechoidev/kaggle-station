#!/usr/bin/env python3
"""swarm/hub/tick.py - the hub pass (cron every 5 min on the always-on hub host; no model, no credits).

  1. pull coordinator request files from hosts that have "coordinator": true (hub/requests/*.json there), apply the
     allow-listed ones to the master config (hub/config.json here) or as flag files, return results (requests_done/)
  2. decide which daemon singletons may start (no other host reported them running in the last 20 min)
  3. run swarm/hub/host.py tick here and, over ssh, on every host with an "ssh" entry
  4. ledger: merge hub/outgoing/ (here) and hub/incoming/<host>/ (pulled from ssh hosts, pushed by push-only hosts
     such as a laptop) into hub/ledger/results/ (newest wins per file name)
  5. copy config, providers, ledger, host reports (incl. the laptop heartbeat) and status to the ssh hosts; pull their
     coordinator logs (hub/coord/) and alerts
  6. write the status page hub/www/{index.html,status.json}
Usage: SWARM_ROOT=/path python3 -I swarm/hub/tick.py   ($SWARM_ROOT/hub/HUB_STOP = do nothing)
"""
import datetime as dt, fcntl, glob, html, json, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import host as H  # noqa: E402

ROOT, HUB, W = H.ROOT, H.HUB, H.W


def log(msg):
    os.makedirs(os.path.join(HUB, 'log'), exist_ok=True)
    with open(os.path.join(HUB, 'log', 'hub.log'), 'a') as f:
        f.write('%s %s\n' % (H.now().strftime('%F %H:%M:%SZ'), msg))


def ssh(target, cmd, timeout=900):
    r = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20', target, cmd], capture_output=True,
                       text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def rsync(src, dst, extra=()):
    r = subprocess.run(['rsync', '-a', '--timeout=120'] + list(extra) + [src, dst], capture_output=True, text=True,
                       timeout=900)
    if r.returncode and r.returncode != 23:
        log('rsync %s -> %s rc %d: %s' % (src, dst, r.returncode, r.stderr.strip()[-200:]))
    return r.returncode


def rroot(c, h):
    return (c['hosts'][h].get('root') or ROOT).rstrip('/')


def ssh_hosts(c, me):
    return [h for h, v in (c.get('hosts') or {}).items() if v.get('ssh') and h != me]


# ------------------------------------------------------------------ requests
def apply_requests(c, me):
    rin, rdone = os.path.join(HUB, 'requests_in'), os.path.join(HUB, 'requests_done')
    os.makedirs(rin, exist_ok=True); os.makedirs(rdone, exist_ok=True)
    srcs = {}
    for h in ssh_hosts(c, me):
        if c['hosts'][h].get('coordinator'):
            d = os.path.join(rin, h); os.makedirs(d, exist_ok=True)
            rsync('%s:%s/hub/requests/' % (c['hosts'][h]['ssh'], rroot(c, h)), d + '/',
                  ['--remove-source-files', '--include=*.json', '--exclude=*'])
            srcs[h] = d
    srcs[me] = os.path.join(HUB, 'requests')
    provs = H.load(os.path.join(ROOT, c.get('providers_file', 'hub/providers.json')), {}) or {}
    changed = False
    for h, d in srcs.items():
        for p in sorted(glob.glob(os.path.join(d, '*.json'))):
            q = H.load(p, {}) or {}
            act, ag = q.get('action'), q.get('agent')
            ws = {w['agent']: w for w in c.get('workers', [])}
            res = 'refused: unknown action'
            try:
                if act == 'set_provider':
                    if q.get('provider') not in provs:
                        res = 'refused: provider not defined'
                    else:
                        tg = list(ws) if ag in ('*', None) else [ag]
                        for a in tg:
                            if a in ws and ws[a].get('watch'):
                                ws[a]['provider'] = q['provider']
                        if ag in ('*', None):
                            c['default_provider'] = q['provider']
                        changed, res = True, 'ok: %s -> %s' % (tg, q['provider'])
                elif act == 'watch' and ag in ws:
                    ws[ag]['watch'] = bool(q.get('on')); changed, res = True, 'ok'
                elif act == 'add_worker':
                    hh = q.get('host')
                    n_on = sum(1 for w in c['workers'] if w.get('host') == hh)
                    cap = int((c.get('max_workers_per_host') or {}).get(hh, 0))
                    if hh not in c.get('hosts', {}) or ag in ws or n_on >= cap:
                        res = 'refused: unknown host, name in use, or max_workers_per_host reached'
                    else:
                        c['workers'].append(dict(agent=ag, host=hh, adapter=q.get('adapter') or c.get('default_adapter'),
                                                 provider=q.get('provider') or c.get('default_provider'),
                                                 args=c.get('default_worker_args', []), watch=True, added=H.iso()))
                        changed, res = True, 'ok'
                elif act in ('stop_worker', 'start_worker') and ag in ws:
                    wh = ws[ag]['host']
                    rel = 'work/agents/%s/STOP' % ag
                    if wh == me:
                        p2 = os.path.join(ROOT, rel)
                        if act == 'stop_worker':
                            os.makedirs(os.path.dirname(p2), exist_ok=True)
                            with open(p2, 'w') as f:
                                f.write('coordinator: %s\n' % q.get('why', ''))
                        elif os.path.exists(p2):
                            os.remove(p2)
                        res = 'ok'
                    elif c['hosts'].get(wh, {}).get('ssh'):
                        cmd = ('mkdir -p %s/work/agents/%s && echo "coordinator: stop" > %s/%s' % (rroot(c, wh), ag, rroot(c, wh), rel)
                               if act == 'stop_worker' else 'rm -f %s/%s' % (rroot(c, wh), rel))
                        res = 'ok' if ssh(c['hosts'][wh]['ssh'], cmd)[0] == 0 else 'failed'
                    else:
                        res = 'refused: host not reachable from the hub'
                elif act in ('scheduler_stop', 'scheduler_resume') and c.get('scheduler_stop_file'):
                    sp = os.path.join(ROOT, c['scheduler_stop_file'])
                    if act == 'scheduler_stop':
                        with open(sp, 'w') as f:
                            f.write('coordinator: %s\n' % q.get('why', ''))
                        res = 'ok'
                    elif os.path.exists(sp) and open(sp).read().startswith('coordinator:'):
                        os.remove(sp); res = 'ok'
                    else:
                        res = 'refused: not stopped by the coordinator'
                elif act == 'self_update_now':
                    hh = q.get('host') or me
                    if hh == me:
                        H.save(os.path.join(HUB, 'self_update_last.json'), {'t': 0}); res = 'ok'
                    elif c['hosts'].get(hh, {}).get('ssh'):
                        res = 'ok' if ssh(c['hosts'][hh]['ssh'], "echo '{\"t\": 0}' > %s/hub/self_update_last.json" % rroot(c, hh))[0] == 0 else 'failed'
                elif act == 'provider_def':
                    dd = q.get('def') or {}
                    if q.get('name') and str(dd.get('url', '')).startswith('https://') and dd.get('model') and \
                            (dd.get('key') is None or str(dd['key']).startswith('~/.config/')):
                        provs[q['name']] = dd
                        H.save(os.path.join(ROOT, c.get('providers_file', 'hub/providers.json')), provs); res = 'ok'
                    else:
                        res = 'refused: needs name, https url, model, key path under ~/.config/'
                elif act == 'note':
                    res = 'ok'
            except Exception as e:
                res = 'error: %s' % e
            q.update(_result=res, _applied=H.iso(), _from=h)
            H.save(os.path.join(rdone, os.path.basename(p)), q)
            os.remove(p)
            log('request %s from %s: %s' % (os.path.basename(p), h, res))
    if changed:
        H.save(H.CONF, c)
    for h in srcs:
        if h != me:
            rsync(rdone + '/', '%s:%s/hub/requests_done/' % (c['hosts'][h]['ssh'], rroot(c, h)))
    return c


# ------------------------------------------------------------------ ledger + status
def merge_ledger():
    L = os.path.join(HUB, 'ledger', 'results')
    os.makedirs(L, exist_ok=True)
    n = 0
    for s in [os.path.join(HUB, 'outgoing')] + sorted(glob.glob(os.path.join(HUB, 'incoming', '*'))):
        for p in glob.glob(os.path.join(s, 'results', '*.json')):
            d = os.path.join(L, os.path.basename(p))
            if not os.path.exists(d) or os.path.getmtime(d) < os.path.getmtime(p):
                shutil.copy2(p, d + '.tmp'); os.replace(d + '.tmp', d); n += 1
    return n


def may_start(c, host):
    ok = []
    for name, s in (c.get('singletons') or {}).items():
        if s.get('type', 'daemon') != 'daemon' or s.get('host') != host:
            continue
        busy = False
        for p in glob.glob(os.path.join(HUB, 'hosts', '*.json')):
            if os.path.basename(p)[:-5] == host:
                continue
            r = H.load(p, {}) or {}
            try:
                fresh = time.time() - dt.datetime.fromisoformat(r['t']).timestamp() < 1200
            except Exception:
                fresh = False
            if fresh and any(g['name'] == name and g.get('pids') for g in r.get('singletons', [])):
                busy = True
        if not busy:
            ok.append(name)
    return ok


def tail(p, n):
    try:
        with open(p, errors='replace') as f:
            return f.read().splitlines()[-n:]
    except OSError:
        return []


def status_page(c):
    hosts = {}
    for p in glob.glob(os.path.join(HUB, 'hosts', '*.json')):
        r = H.load(p, {}) or {}
        try:
            r['age_min'] = round((time.time() - dt.datetime.fromisoformat(r['t']).timestamp()) / 60, 1)
        except Exception:
            r['age_min'] = None
        hosts[os.path.basename(p)[:-5]] = r
    acct = {}
    if c.get('status_cmd'):
        try:
            acct = json.loads(subprocess.run(c['status_cmd'], shell=True, cwd=ROOT, capture_output=True, text=True,
                                             timeout=120).stdout or '{}')
        except Exception as e:
            acct = {'error': str(e)[:200]}
    per = {}
    for p in glob.glob(os.path.join(HUB, 'ledger', 'results', '*.json')):
        age = time.time() - os.path.getmtime(p)
        if age <= 86400:
            h = (H.load(p, {}) or {}).get('host', '?')
            e = per.setdefault(h, {'last_1h': 0, 'last_24h': 0}); e['last_24h'] += 1
            if age <= 3600:
                e['last_1h'] += 1
    alerts = sorted(l for p in glob.glob(os.path.join(HUB, 'alerts', '*.txt')) for l in tail(p, 10))[-20:]
    lap = [h for h, v in (c.get('hosts') or {}).items() if v.get('push_only')]
    st = dict(t=H.iso(), default_provider=c.get('default_provider'), hosts=hosts, account=acct, results=per,
              alerts=alerts, coord=sum((tail(p, 30) for p in sorted(glob.glob(os.path.join(HUB, 'coord', '*', 'log.md')) + glob.glob(os.path.join(HUB, 'coord', 'log.md')))), [])[-30:],
              owner_present=any((hosts.get(h, {}).get('age_min') or 1e9) <= 15 for h in lap))
    H.save(os.path.join(HUB, 'status.json'), st)
    H.save(os.path.join(HUB, 'www', 'status.json'), st)
    e = html.escape
    rows = []
    for hn, r in sorted(hosts.items()):
        rows.append('<tr><th colspan=7>%s: report %s min old, load %s, mem %s MB, flags %s</th></tr>' % (
            e(hn), r.get('age_min'), e(str([round(x, 2) for x in r.get('load', [])])), r.get('mem_avail_mb'),
            e(','.join(r.get('flags', [])) or '-')))
        for w in r.get('workers', []):
            s = w.get('status') or {}
            rows.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s/%s/%s</td><td>%s</td><td>%s</td></tr>' % (
                e(w['agent']), 'up' if w.get('running') else '<b>down</b>', e(str(w.get('provider') or w.get('want_provider'))),
                e(str(s.get('phase'))), s.get('passes'), s.get('submits'), s.get('giveups'), e(str(s.get('stop') or '')),
                e(str(w.get('decision') or ''))))
        for g in r.get('singletons', []):
            rows.append('<tr><td>%s</td><td colspan=6>%s (assigned %s)</td></tr>' % (e(g['name']), e(str(g.get('state'))), e(str(g.get('assigned')))))
    page = ('<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="120">'
            '<meta name="viewport" content="width=device-width, initial-scale=1"><title>swarm status</title><style>'
            ':root{--bg:#fff;--fg:#111;--line:#ddd}@media (prefers-color-scheme: dark){:root{--bg:#111;--fg:#eee;--line:#333}}'
            'body{background:var(--bg);color:var(--fg);font:14px system-ui,sans-serif;margin:16px}table{border-collapse:collapse;width:100%%}'
            'td,th{border-bottom:1px solid var(--line);padding:3px 6px;text-align:left}pre{white-space:pre-wrap}</style></head><body>'
            '<h1>swarm</h1><p>%s UTC. Owner present: %s. Default provider: %s.</p><h2>Account</h2><pre>%s</pre>'
            '<h2>Hosts and workers (passes/submits/give-ups)</h2><table>%s</table><h2>Results by host</h2><pre>%s</pre>'
            '<h2>Alerts</h2><pre>%s</pre><h2>Coordinator log</h2><pre>%s</pre></body></html>') % (
        e(st['t']), st['owner_present'], e(str(st['default_provider'])), e(json.dumps(acct, indent=1)), ''.join(rows),
        e(json.dumps(per, indent=1)), e('\n'.join(alerts) or '-'), e('\n'.join(st['coord']) or '-'))
    os.makedirs(os.path.join(HUB, 'www'), exist_ok=True)
    with open(os.path.join(HUB, 'www', 'index.html.tmp'), 'w') as f:
        f.write(page)
    os.replace(os.path.join(HUB, 'www', 'index.html.tmp'), os.path.join(HUB, 'www', 'index.html'))


def main():
    os.makedirs(HUB, exist_ok=True)
    lk = open(os.path.join(HUB, '.hub_tick.lock'), 'w')
    try:
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print('another hub tick is running'); return
    if os.path.exists(os.path.join(HUB, 'HUB_STOP')):
        log('HUB_STOP present: nothing done'); return
    t0 = time.time()
    c = H.conf()
    me = H.me(c)
    c = apply_requests(c, me)
    r = subprocess.run([sys.executable, '-I', os.path.join(HERE, 'host.py'), 'tick', '--may-start', ','.join(may_start(c, me))],
                       cwd=ROOT, env=dict(os.environ, SWARM_ROOT=ROOT), capture_output=True, text=True, timeout=3600)
    if r.returncode:
        log('local tick rc %d: %s' % (r.returncode, r.stderr.strip()[-300:]))
    for h in ssh_hosts(c, me):
        t, rr = c['hosts'][h]['ssh'], rroot(c, h)
        rc, out, err = ssh(t, 'cd %s && SWARM_ROOT=%s python3 -I swarm/hub/host.py tick --may-start "%s"' % (
            rr, rr, ','.join(may_start(c, h))), timeout=3600)
        if rc:
            log('%s tick rc %d: %s' % (h, rc, err.strip()[-300:])); continue
        try:
            rep = json.loads(out.strip().splitlines()[-1])
            if not rep.get('busy'):
                H.save(os.path.join(HUB, 'hosts', '%s.json' % h), rep)
        except Exception as e:
            log('%s report unreadable: %s' % (h, e))
        os.makedirs(os.path.join(HUB, 'incoming', h), exist_ok=True)
        rsync('%s:%s/hub/outgoing/' % (t, rr), os.path.join(HUB, 'incoming', h) + '/')
    n = merge_ledger()
    for h in ssh_hosts(c, me):
        t, rr = c['hosts'][h]['ssh'], rroot(c, h)
        rsync(os.path.join(HUB, 'ledger') + '/', '%s:%s/hub/ledger/' % (t, rr))
        files = [os.path.join(HUB, x) for x in ('config.json', 'status.json') if os.path.exists(os.path.join(HUB, x))]
        pf = os.path.join(ROOT, c.get('providers_file', 'hub/providers.json'))
        push = files + ([pf] if os.path.exists(pf) else [])
        if push:
            subprocess.run(['rsync', '-a', '--timeout=120'] + push + ['%s:%s/hub/' % (t, rr)], capture_output=True, timeout=900)
        subprocess.run(['rsync', '-a', '--timeout=120', os.path.join(HUB, 'hosts') + '/', '%s:%s/hub/hosts/' % (t, rr)],
                       capture_output=True, timeout=900)
        os.makedirs(os.path.join(HUB, 'coord', h), exist_ok=True)
        rsync('%s:%s/hub/coord/' % (t, rr), os.path.join(HUB, 'coord', h) + '/')
        rsync('%s:%s/hub/alerts/%s.txt' % (t, rr, h), os.path.join(HUB, 'alerts', '%s.txt' % h), ['--ignore-missing-args'])
    try:
        status_page(c)
    except Exception as e:
        log('status page failed: %s' % e)
    log('tick %.0f s: ledger +%d' % (time.time() - t0, n))


if __name__ == '__main__':
    main()
