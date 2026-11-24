#!/usr/bin/env python3
"""swarm/coord/triggers.py HUB_DIR ROUTINE_H - print the trigger text for patrol.sh (empty = nothing to do),
or OWNER_PRESENT when a push-only host reported in the last 15 min. Keeps its memory in HUB_DIR/coord/trigger_state.json."""
import datetime as dt, glob, json, os, sys, time

H, RH = sys.argv[1], float(sys.argv[2])
ST = os.path.join(H, 'coord', 'trigger_state.json')


def load(p, d):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return d


def age_min(t):
    try:
        return (time.time() - dt.datetime.fromisoformat(t).timestamp()) / 60
    except Exception:
        return 1e9


st, now, out = load(ST, {}), time.time(), []
s = load(os.path.join(H, 'status.json'), {})
cfg = load(os.path.join(H, 'config.json'), {})
for name, h in (cfg.get('hosts') or {}).items():
    if h.get('push_only') and age_min(load(os.path.join(H, 'hosts', name + '.json'), {}).get('t')) <= 15:
        print('OWNER_PRESENT'); sys.exit()
if age_min(s.get('t')) > 20:
    out.append('hub status is %.0f min old (hub down?)' % age_min(s.get('t')))
al = sorted(l for p in glob.glob(os.path.join(H, 'alerts', '*.txt')) for l in open(p, errors='replace').read().splitlines())
if al and al[-1] != st.get('last_alert'):
    out.append('new alert: ' + al[-1][:200]); st['last_alert'] = al[-1]
for hn, r in (s.get('hosts') or {}).items():
    k = 'stale_' + hn
    if 'VERIFIER_STALE' in r.get('flags', []):
        st.setdefault(k, now)
        if now - st[k] > 1800:
            out.append('VERIFIER_STALE on %s for %.0f min' % (hn, (now - st[k]) / 60))
    else:
        st.pop(k, None)
    for w in r.get('workers', []):
        stop = str((w.get('status') or {}).get('stop') or '')
        if stop in ('LLM_DEAL_ENDED', 'LLM_COST'):
            out.append('%s on %s stopped with %s' % (w['agent'], hn, stop))
        dec, k = str(w.get('decision') or ''), 'down_' + w['agent']
        if w.get('watch') and not w.get('running') and any(x in dec for x in ('not restarted', 'cap', 'held')):
            st.setdefault(k, now)
            if now - st[k] > 900:
                out.append('%s on %s down: %s' % (w['agent'], hn, dec))
        else:
            st.pop(k, None)
if now - st.get('last_patrol', 0) > RH * 3600:
    out.append('routine patrol')
key = '|'.join(sorted(out))
if out and (key != st.get('last_key') or now - st.get('last_patrol', 0) > 3600):
    st['last_key'], st['last_patrol'] = key, now
    print('; '.join(out))
os.makedirs(os.path.dirname(ST), exist_ok=True)
with open(ST, 'w') as f:
    json.dump(st, f)
