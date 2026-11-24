"""swarm/adapters/pytests_example.py - example workload: write a Python function that passes given unit tests.

Runs out of the box (no external project): items come from a JSON task file, the checker runs the tests, results go
to <SWARM_ROOT>/work/results/. It exists to show the adapter interface and to smoke-test a provider end to end.

SAFETY: the model's code is executed (python3 -I, a temporary directory, a timeout, an empty environment). That is
enough for a demo with a reputable provider, not a sandbox. For real use run workers in a container or a VM.

Adapter interface (what swarm/worker.py calls):
  key(item) -> str                       a stable id
  practice_items(n) -> [item]            phase A: offline items with known answers (optional)
  get_item() -> item | None              phase B: take (claim) the next item; None = nothing left
  build_prompt(item, history) -> messages   history = [(candidate, feedback), ...] from earlier rounds
  extract(reply) -> candidate            optional; default = the longest fenced code block
  verify(item, candidate) -> (ok, feedback, score)   score: lower is closer (or None)
  submit(item, candidate) -> (ok, info)
  give_up(item, best_candidate, reason)
  release(item)                          hand a held item back (exit, error)
Adapter args (--adapter-arg KEY=VALUE): tasks=<json file> (default: tasks_example.json next to this file).
"""
import fcntl, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.environ.get('SWARM_ROOT', '.'))

SYSTEM = ('You write Python 3 code. Answer with ONE fenced ```python code block that defines the requested function '
          '(and any helpers). No tests, no prints, no input().')


class Adapter:
    def __init__(self, args, log):
        self.log = log
        self.tasks = json.load(open(args.adapter_args.get('tasks', os.path.join(HERE, 'tasks_example.json'))))
        self.res = os.path.join(ROOT, 'work', 'results')
        os.makedirs(os.path.join(self.res, 'giveup'), exist_ok=True)
        self.lockf = os.path.join(self.res, '.taken.lock')

    def key(self, item):
        return item['id']

    def practice_items(self, n):
        return [t for t in self.tasks if t.get('practice')][:n]

    def get_item(self):
        """claim: the first live task nobody has taken (a shared file under flock = a tiny pool)"""
        with open(self.lockf, 'a+') as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            lf.seek(0)
            taken = set(lf.read().split())
            for t in self.tasks:
                if not t.get('practice') and t['id'] not in taken:
                    lf.write(t['id'] + '\n'); lf.flush()
                    return t
        return None

    def build_prompt(self, item, history):
        user = 'Write `%s`.\n%s\n\nThese tests must pass:\n```python\n%s\n```' % (item['signature'], item['description'],
                                                                              item['tests'])
        msgs = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': user}]
        if history:
            cand, fb = history[-1]
            msgs += [{'role': 'assistant', 'content': '```python\n%s```' % cand},
                     {'role': 'user', 'content': 'The tests failed:\n%s\nFix the code and answer with the complete code '
                                                 'block.' % str(fb)[-1500:]}]
        return msgs

    def verify(self, item, cand):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'check.py')
            with open(p, 'w') as f:
                f.write(cand + '\n\n' + item['tests'] + '\nprint("ALL TESTS PASSED")\n')
            try:
                r = subprocess.run([sys.executable, '-I', p], cwd=d, capture_output=True, text=True, timeout=10,
                                   env={'PATH': '/usr/bin:/bin'})
            except subprocess.TimeoutExpired:
                return False, 'timed out after 10 s (infinite loop?)', 1e6
        ok = r.returncode == 0 and 'ALL TESTS PASSED' in r.stdout
        fb = (r.stderr or r.stdout).strip()[-1500:]
        n_fail = fb.count('AssertionError') + fb.count('Error')
        return ok, fb or 'ok', 0 if ok else max(1, n_fail)

    def submit(self, item, cand):
        p = os.path.join(self.res, '%s.json' % item['id'])
        with open(p, 'w') as f:
            json.dump(dict(item=item['id'], result=cand), f)
        return True, p

    def give_up(self, item, best, reason):
        with open(os.path.join(self.res, 'giveup', '%s.json' % item['id']), 'w') as f:
            json.dump(dict(item=item['id'], reason=reason, best=best), f)

    def release(self, item):
        with open(self.lockf, 'a+') as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            lf.seek(0)
            keep = [x for x in lf.read().split() if x != item['id']]
            lf.seek(0); lf.truncate(); lf.write(''.join(x + '\n' for x in keep))
