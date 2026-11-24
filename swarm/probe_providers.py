#!/usr/bin/env python3
"""swarm/probe_providers.py - probe and rank free-model providers (read-only; never prints keys).

Reads a providers file {name: {url, model, key (PATH of a bearer key file, or null), extra, attr}}
(default: $SWARM_ROOT/hub/providers.json, else swarm/providers.json). Per provider:
  1. key file present?  2. GET <url>/models: model listed? price 0 where the provider publishes prices?
  3. a tiny chat request: HTTP code, latency, rate-limit headers, usage.cost
  4. a ~120-token request: seconds, tokens/s, finish reason, reasoning leak (reasoning_content present = the
     reasoning-off parameter in "extra" is wrong for this provider), empty answer
  5. --yield-cmd: YOUR offline yield test, e.g.
       --yield-cmd 'python3 -I swarm/yield_test.py --provider {provider} --providers {providers}'
     whose last stdout line is JSON {"passed": N, "total": M, "closest": X} (lower X = closer).
Ranking: usable first, then passed, then closest, then seconds per answer, then the request limit.
Prints a table and "CHOICE <name>" (exit 0), or "CHOICE none" (exit 2). --json for scripts.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.environ.get('SWARM_ROOT', '.'))


def default_file():
    for p in (os.path.join(ROOT, 'hub', 'providers.json'), os.path.join(HERE, 'providers.json')):
        if os.path.exists(p):
            return p


def call(url, key, body=None, timeout=180):
    hdr = {'User-Agent': 'swarm-provider-probe/1', 'Content-Type': 'application/json'}
    if key:
        hdr['Authorization'] = 'Bearer ' + key
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=hdr,
                                 method='POST' if body is not None else 'GET')
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
            h = {k.lower(): v for k, v in r.headers.items()}
            return r.status, d, h, time.time() - t0
    except urllib.error.HTTPError as e:
        try:
            d = json.loads(e.read().decode('utf-8', 'replace') or '{}')
        except Exception:
            d = {}
        return e.code, d, {k.lower(): v for k, v in (e.headers or {}).items()}, time.time() - t0
    except Exception as e:
        return 0, {'error': str(e)[:200]}, {}, time.time() - t0


def scrub(x, key):
    """never let a key reach the output, even if a provider echoes it"""
    s = json.dumps(x, default=str)
    return json.loads(s.replace(key, '***')) if key and key in s else x


def probe(name, p, ycmd, ytimeout):
    r = dict(name=name, model=p.get('model'), url=p.get('url'))
    key = None
    if p.get('key'):
        kp = os.path.expanduser(p['key'])
        if not os.path.isfile(kp):
            r.update(usable=False, why='no key file (%s)' % p.get('key')); return r
        with open(kp) as f:
            key = f.read().strip()
    base = p['url'].rstrip('/')
    code, d, h, el = call(base + '/models', key, timeout=60)
    r['models_http'] = code
    if code == 200 and isinstance(d.get('data'), list):
        m = [x for x in d['data'] if x.get('id') == p['model']]
        r['listed'] = bool(m)
        if m and isinstance(m[0].get('pricing'), dict):
            try:
                r['price'] = sum(float(v) for k, v in m[0]['pricing'].items() if k in ('prompt', 'completion'))
            except (TypeError, ValueError):
                pass
    extra = p.get('extra') or {}
    body = dict(model=p['model'], messages=[{'role': 'user', 'content': 'Reply with the single word OK.'}], max_tokens=16,
                temperature=0, **extra)
    code, d, h, el = call(base + '/chat/completions', key, body)
    r['tiny_http'], r['tiny_s'] = code, round(el, 2)
    r['ratelimit'] = {k: v for k, v in h.items() if 'ratelimit' in k}
    if code != 200:
        r.update(usable=False, why='chat HTTP %s: %s' % (code, json.dumps(d)[:160])); return scrub(r, key)
    us = d.get('usage') or {}
    r['cost'] = us.get('cost', us.get('total_cost'))
    body = dict(model=p['model'], temperature=0.2, max_tokens=400, **extra, messages=[{'role': 'user', 'content':
                'Write a C++ function `int sum(const int* a, int n)` that returns the sum of the array, then a second '
                'function that returns the maximum. Answer with code only.'}])
    code, d, h, el = call(base + '/chat/completions', key, body)
    r['speed_http'], r['speed_s'] = code, round(el, 2)
    if code == 200:
        msg = (d.get('choices') or [{}])[0].get('message') or {}
        us = d.get('usage') or {}
        ct = us.get('completion_tokens') or 0
        r.update(completion_tokens=ct, tok_s=round(ct / el, 1) if el and ct else None,
                 finish=(d.get('choices') or [{}])[0].get('finish_reason'),
                 reasoning_leak=bool(msg.get('reasoning_content') or msg.get('reasoning')),
                 empty=not (msg.get('content') or '').strip())
        c2 = us.get('cost', us.get('total_cost'))
        if c2 is not None:
            r['cost'] = max(float(r.get('cost') or 0), float(c2 or 0))
    lim = [v for k, v in r['ratelimit'].items() if k.endswith('limit-requests') or k == 'x-ratelimit-limit']
    try:
        r['req_limit'] = int(lim[0]) if lim else None
    except ValueError:
        r['req_limit'] = None
    why = []
    if r.get('listed') is False:
        why.append('model not listed')
    if r.get('price') not in (None, 0, 0.0):
        why.append('price %s' % r['price'])
    if r.get('cost') not in (None, 0, 0.0, '0'):
        why.append('cost %s' % r['cost'])
    if code != 200:
        why.append('speed HTTP %s' % code)
    if r.get('reasoning_leak'):
        why.append('reasoning not switched off (fix "extra")')
    if r.get('empty'):
        why.append('empty answer')
    r['usable'] = not why
    r['why'] = '; '.join(why) or 'ok'
    if ycmd and r['usable']:
        r.update(yield_test(name, ycmd, ytimeout))
    return scrub(r, key)


def yield_test(name, cmd_tpl, timeout):
    """run the user's own offline yield test; its last stdout line must be JSON {"passed", "total", "closest"}"""
    cmd = cmd_tpl.replace('{provider}', name).replace('{providers}', A.file)
    t0 = time.time()
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        out = [l for l in r.stdout.splitlines() if l.strip().startswith('{')]
        d = json.loads(out[-1]) if out else {}
    except subprocess.TimeoutExpired:
        d = {'note': 'timeout'}
    except ValueError:
        d = {'note': 'no JSON summary line'}
    return dict(yield_passed=d.get('passed'), yield_total=d.get('total'), yield_closest=d.get('closest'),
                yield_s=round(time.time() - t0), yield_note=d.get('note'))


def rank_key(r):
    cs = r.get('yield_closest')
    return (0 if r.get('usable') else 1, -(r.get('yield_passed') or 0), cs if cs is not None else 1e9,
            r.get('speed_s') or 1e9, -(r.get('req_limit') or 0))


def main():
    global A
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', default=default_file())
    ap.add_argument('--only')
    ap.add_argument('--yield-cmd', help="your offline yield test; {provider} and {providers} are substituted; last stdout line JSON {passed,total,closest}")
    ap.add_argument('--yield-timeout', type=int, default=900)
    ap.add_argument('--json', action='store_true')
    A = ap.parse_args()
    provs = {k: v for k, v in json.load(open(A.file)).items() if not k.startswith('_') and isinstance(v, dict)}
    if A.only:
        provs = {k: v for k, v in provs.items() if k in A.only.split(',')}
    res = sorted((probe(k, v, A.yield_cmd, A.yield_timeout) for k, v in provs.items()), key=rank_key)
    if A.json:
        print(json.dumps(res, indent=1, default=str))
    else:
        print('%-20s %-6s %-7s %-7s %-6s %-8s %-6s %s' % ('provider', 'usable', 'tiny_s', 'speed_s', 'tok/s', 'reqlim', 'yield(p/n~close)', 'why'))
        for r in res:
            print('%-20s %-6s %-7s %-7s %-6s %-8s %-6s %s' % (
                r['name'], r.get('usable'), r.get('tiny_s', '-'), r.get('speed_s', '-'), r.get('tok_s', '-'),
                r.get('req_limit', '-'), '%s/%s~%s' % (r.get('yield_passed'), r.get('yield_total'), r.get('yield_closest')) if 'yield_passed' in r else '-',
                r.get('why')))
    best = next((r['name'] for r in res if r.get('usable')), None)
    print('CHOICE %s' % (best or 'none (no usable free provider)'))
    return 0 if best else 2


A = None
if __name__ == '__main__':
    sys.exit(main())
