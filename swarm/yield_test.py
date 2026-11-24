#!/usr/bin/env python3
"""swarm/yield_test.py - mini yield test for probe_providers.py --yield-cmd: phase A only, in a throw-away SWARM_ROOT.

Runs swarm/worker.py --phase A on the adapter's practice items (nothing is claimed or submitted) and prints one JSON
line {"passed": N, "total": M, "closest": X} (X = mean score of the answers, lower is closer; null if unknown).
Usage: python3 -I swarm/yield_test.py --provider NAME --providers FILE [--adapter PATH] [--n 3] [--rounds 2]
"""
import argparse, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument('--provider', required=True)
ap.add_argument('--providers', required=True)
ap.add_argument('--adapter', default=os.path.join(HERE, 'adapters', 'pytests_example.py'))
ap.add_argument('--adapter-arg', action='append', default=[])
ap.add_argument('--n', type=int, default=3)
ap.add_argument('--rounds', type=int, default=2)
ap.add_argument('--timeout', type=int, default=900)
a = ap.parse_args()
root = tempfile.mkdtemp(prefix='swarm_yield_')
cmd = [sys.executable, '-I', os.path.join(HERE, 'worker.py'), '--provider', a.provider, '--providers',
       os.path.abspath(a.providers), '--adapter', os.path.abspath(a.adapter), '--agent', 'YIELD', '--phase', 'A',
       '--practice-n', str(a.n), '--rounds', str(a.rounds)]
for x in a.adapter_arg:
    cmd += ['--adapter-arg', x]
try:
    subprocess.run(cmd, env=dict(os.environ, SWARM_ROOT=root), capture_output=True, text=True, timeout=a.timeout)
except subprocess.TimeoutExpired:
    pass
st, scores = {}, []
try:
    with open(os.path.join(root, 'work', 'agents', 'YIELD', 'status.json')) as f:
        st = json.load(f)
    with open(os.path.join(root, 'work', 'agents', 'YIELD', 'answers.jsonl')) as f:
        scores = [json.loads(l).get('score') for l in f]
except OSError:
    pass
sc = [s for s in scores if isinstance(s, (int, float))]
print(json.dumps(dict(passed=st.get('passes'), total=st.get('items'), closest=round(sum(sc) / len(sc), 2) if sc else None,
                      root=root)))
