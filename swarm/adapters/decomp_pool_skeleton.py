"""swarm/adapters/decomp_pool_skeleton.py - SKELETON adapter for a byte-matching decompilation project with a pool API.

Fill in every `TODO`. The shape follows a typical pool: claim a function (returns a claim id, the function's
metadata, the compile flags and a checker pack), submit source on a match, give up with the best attempt and a reason.
The checker is the project's own (compile with the original compiler and flags, compare machine code); this file only
calls it. Keep the pool key in a file (POOL_KEY_FILE) and never log it.

Adapter args: pool=<base URL>, key_file=<path>, checker=<command template>, band=<size band or queue name>.
"""
import json, os, re, subprocess, tempfile, urllib.request

ROOT = os.path.abspath(os.environ.get('SWARM_ROOT', '.'))

SYSTEM = ('You write C/C++ for a matching decompilation. The source is compiled with the given compiler and flags and '
          'must produce exactly the original machine code. Answer with ONE complete fenced code block.')


class Adapter:
    def __init__(self, args, log):
        a = args.adapter_args
        self.log = log
        self.pool = a.get('pool', 'https://TODO-pool.example/api/v1/')
        self.key_file = os.path.expanduser(a.get('key_file', '~/.config/TODO/pool_key'))
        self.checker = a.get('checker', 'TODO-checker --source {src} --pack {pack} --json')
        self.band = a.get('band', 'small')
        self.work = os.path.join(ROOT, 'work', 'items')
        os.makedirs(self.work, exist_ok=True)

    # -------------------------------------------------------------- pool API (TODO: match your project's API)
    def _api(self, tool, body):
        with open(self.key_file) as f:
            key = f.read().strip()
        req = urllib.request.Request(self.pool + tool, data=json.dumps(body).encode(), method='POST',
                                     headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=120) as r:   # TODO: retries, 409/429 handling, daily-cap detection
            return json.load(r)

    def key(self, item):
        return item['address']

    def practice_items(self, n):
        # TODO: a few functions you already matched (source known) with their packs, to prove provider + checker.
        return []

    def get_item(self):
        d = self._api('claim', {'band': self.band})                     # TODO: your claim call
        if not d.get('claim_id'):
            return None                                                  # TODO: distinguish "pool empty" from refusals
        item = dict(address=d['address'], claim_id=d['claim_id'], listing=d.get('disassembly', ''),
                    flags=d.get('flags'), dir=os.path.join(self.work, d['address']))
        os.makedirs(item['dir'], exist_ok=True)
        # TODO: unpack the checker pack from the claim into item['dir'] + '/pack'
        return item

    # -------------------------------------------------------------- prompt / verify
    def build_prompt(self, item, history):
        user = 'Target function %s, compiler flags %s.\nOriginal listing:\n%s' % (item['address'], item['flags'],
                                                                                item['listing'])
        msgs = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': user}]
        if history:
            cand, fb = history[-1]
            msgs += [{'role': 'assistant', 'content': '```cpp\n%s```' % cand},
                     {'role': 'user', 'content': 'Checker result:\n%s\nFix it; answer with the complete file.' % fb}]
        return msgs

    def verify(self, item, cand):
        with tempfile.NamedTemporaryFile('w', suffix='.cpp', dir=item['dir'], delete=False) as f:
            f.write(cand)
        cmd = self.checker.format(src=f.name, pack=os.path.join(item['dir'], 'pack'))
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
        try:
            res = json.loads(r.stdout)                                   # TODO: your checker's output format
        except ValueError:
            return False, (r.stdout + r.stderr)[-1500:], None
        ok = res.get('status') == 'match' and not res.get('refused')
        diff = res.get('differing_instructions')
        return ok, res.get('diff') or res.get('errors') or str(res)[:1500], diff

    # -------------------------------------------------------------- outcomes
    def submit(self, item, cand):
        # TODO: run project-wide guards first (name uniqueness against the team ledger, refused patterns)
        d = self._api('submit', {'claim_id': item['claim_id'], 'source': cand, 'model': 'TODO model credit'})
        return bool(d.get('submission_id')), d.get('submission_id') or d

    def give_up(self, item, best, reason):
        self._api('giveup', {'claim_id': item['claim_id'], 'reason': reason[:400], 'best_code': best or ''})

    def release(self, item):
        self.give_up(item, None, 'worker stopped before finishing')
