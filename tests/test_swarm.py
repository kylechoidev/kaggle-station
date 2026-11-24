"""Offline tests for swarm/: a stub OpenAI-compatible server, the worker with the example adapter (including a
feedback round), host.py tick (watchdog start + ledger export), hub tick.py (merge + status page), the Kaggle
scheduler in --dry-run with a stub kaggle CLI, and the coordinator triggers. No network, no Kaggle."""
import glob, http.server, json, os, py_compile, stat, subprocess, sys, tempfile, threading, time, unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SW = os.path.join(ROOT, 'swarm')

def jl(p):
    with open(p) as f:
        return json.load(f)


def rd(p):
    with open(p) as f:
        return f.read()


def wr(p, text):
    with open(p, 'w') as f:
        f.write(text)


def jd(obj, p):
    with open(p, 'w') as f:
        json.dump(obj, f)


GOOD = {'def add': 'def add(a, b):\n    return a + b\n', 'def sq': 'def sq(x):\n    return x * x\n'}


class Stub(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self._send({'data': [{'id': 'stub-model', 'pricing': {'prompt': '0', 'completion': '0'}}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        last = body['messages'][-1]['content']
        first = body['messages'][1]['content'] if len(body['messages']) > 1 else last
        code = 'def nothing():\n    pass\n'
        for sig, src in GOOD.items():
            if sig in first:
                code = src
        if 'def sq' in first and 'tests failed' not in last:
            code = 'def sq(x):\n    return x + x\n'          # wrong on purpose: forces one feedback round
        self._send({'choices': [{'message': {'content': '```python\n%s```' % code}, 'finish_reason': 'stop'}],
                    'usage': {'completion_tokens': 20, 'cost': 0}}, {'x-ratelimit-limit': '100'})

    def _send(self, d, hdr=None):
        b = json.dumps(d).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        for k, v in (hdr or {}).items():
            self.send_header(k, v)
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)


class Swarm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Stub)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.tmp = tempfile.mkdtemp(prefix='swarm_test_')
        cls.prov = os.path.join(cls.tmp, 'providers.json')
        with open(cls.prov, 'w') as f:
            json.dump({'stub': {'url': 'http://127.0.0.1:%d/v1' % cls.srv.server_port, 'model': 'stub-model',
                                'key': None, 'extra': {}}}, f)
        cls.tasks = os.path.join(cls.tmp, 'tasks.json')
        with open(cls.tasks, 'w') as f:
            json.dump([{'id': 'p_add', 'practice': True, 'signature': 'def add(a, b)', 'description': 'sum',
                        'tests': 'assert add(2, 3) == 5'},
                       {'id': 't_sq', 'signature': 'def sq(x)', 'description': 'square', 'tests': 'assert sq(3) == 9'}], f)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def run_py(self, args, root, timeout=120, **kw):
        return subprocess.run([sys.executable, '-I'] + args, cwd=ROOT, capture_output=True, text=True, timeout=timeout,
                              env=dict(os.environ, SWARM_ROOT=root), **kw)

    def test_compile(self):
        for p in glob.glob(os.path.join(SW, '**', '*.py'), recursive=True):
            py_compile.compile(p, doraise=True, cfile=os.path.join(self.tmp, 'c.pyc'))

    def test_worker_end_to_end(self):
        root = tempfile.mkdtemp(dir=self.tmp)
        r = self.run_py([os.path.join(SW, 'worker.py'), '--provider', 'stub', '--providers', self.prov, '--adapter',
                         os.path.join(SW, 'adapters', 'pytests_example.py'), '--adapter-arg', 'tasks=' + self.tasks,
                         '--agent', 'T1'], root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        st = jl(os.path.join(root, 'work', 'agents', 'T1', 'status.json'))
        self.assertEqual((st['passes'], st['submits'], st['giveups'], st['final']), (2, 1, 0, True))
        ans = [json.loads(l) for l in rd(os.path.join(root, 'work', 'agents', 'T1', 'answers.jsonl')).splitlines()]
        self.assertEqual([(a['item'], a['round'], a['ok']) for a in ans], [('p_add', 1, True), ('t_sq', 1, False), ('t_sq', 2, True)])
        self.assertTrue(os.path.exists(os.path.join(root, 'work', 'results', 't_sq.json')))

    def test_probe(self):
        r = self.run_py([os.path.join(SW, 'probe_providers.py'), '--file', self.prov], self.tmp)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('CHOICE stub', r.stdout)

    def test_host_tick_and_hub(self):
        root = tempfile.mkdtemp(dir=self.tmp)
        os.makedirs(os.path.join(root, 'hub'))
        os.symlink(SW, os.path.join(root, 'swarm'))
        hn = subprocess.run(['hostname'], capture_output=True, text=True).stdout.strip()
        cfg = {'hosts': {'h': {'hostname': hn, 'ssh': None}}, 'default_provider': 'stub', 'providers_file': 'hub/providers.json',
               'singletons': {'sched': {'type': 'cron', 'host': 'h'}},
               'workers': [{'agent': 'T2', 'host': 'h', 'provider': 'stub', 'adapter': os.path.join(SW, 'adapters', 'pytests_example.py'),
                            'args': ['--adapter-arg', 'tasks=' + self.tasks], 'watch': True}]}
        jd(cfg, os.path.join(root, 'hub', 'config.json'))
        jd(jl(self.prov), os.path.join(root, 'hub', 'providers.json'))
        r = self.run_py([os.path.join(SW, 'hub', 'host.py'), 'tick'], root)
        rep = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertIn('restarted', rep['workers'][0]['decision'])          # never ran = crash -> started
        for _ in range(60):
            st = os.path.join(root, 'work', 'agents', 'T2', 'status.json')
            if os.path.exists(st) and jl(st).get('final'):
                break
            time.sleep(1)
        self.assertTrue(os.path.exists(os.path.join(root, 'work', 'results', 't_sq.json')))
        self.assertEqual(self.run_py([os.path.join(SW, 'hub', 'guard.py'), 'sched'], root).returncode, 0)
        self.assertEqual(self.run_py([os.path.join(SW, 'hub', 'guard.py'), 'nope'], root).returncode, 1)
        r = self.run_py([os.path.join(SW, 'hub', 'tick.py')], root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(root, 'hub', 'ledger', 'results', 't_sq.json')))
        self.assertIn('<h1>swarm</h1>', rd(os.path.join(root, 'hub', 'www', 'index.html')))
        # STOP held: next tick must not restart the (finished) worker while a human STOP exists
        wr(os.path.join(root, 'work', 'agents', 'T2', 'STOP'), 'human\n')
        rep = json.loads(self.run_py([os.path.join(SW, 'hub', 'host.py'), 'tick'], root).stdout.strip().splitlines()[-1])
        self.assertTrue(rep['workers'][0]['decision'].startswith('held'))

    def test_kaggle_sched_dry(self):
        root = tempfile.mkdtemp(dir=self.tmp)
        os.makedirs(os.path.join(root, 'kaggle'))
        cli = os.path.join(root, 'kaggle_stub')
        with open(cli, 'w') as f:
            f.write('#!/bin/sh\ncase "$2" in status) echo "404 not found";; list) echo "ref,title,author,lastRunTime,totalVotes";; esac\n')
        os.chmod(cli, stat.S_IRWXU)
        cfg = jl(os.path.join(SW, 'kaggle', 'sched.example.json'))
        cfg.update(kaggle_cli=cli, relay=None)
        cfg['accounts'] = [{'user': 'someone', 'home': root, 'slots': 5, 'agent_prefix': 'KA'}]
        jd(cfg, os.path.join(root, 'kaggle', 'sched.json'))
        r = self.run_py([os.path.join(SW, 'kaggle', 'kaggle_sched.py'), '--dry-run'], root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count('DRY would push'), 5, r.stdout)
        src = rd(os.path.join(root, 'kaggle', 'push', 'someone-3', 'swarm_kernel.py'))
        self.assertIn('"agent": "KA3"', src)
        wr(os.path.join(root, 'kaggle', 'STOP_ALL'), 'pause\n')
        r = self.run_py([os.path.join(SW, 'kaggle', 'kaggle_sched.py'), '--dry-run'], root)
        self.assertEqual(r.stdout.count('DRY would push'), 0, r.stdout)

    def test_triggers(self):
        h = tempfile.mkdtemp(dir=self.tmp)
        os.makedirs(os.path.join(h, 'alerts'))
        jd({'t': time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime()), 'hosts': {}}, os.path.join(h, 'status.json'))
        wr(os.path.join(h, 'alerts', 'x.txt'), '2026-01-01T00:00:00+00:00 [x] worker W1 stopped with LLM_COST\n')
        r = subprocess.run([sys.executable, '-I', os.path.join(SW, 'coord', 'triggers.py'), h, '6'], capture_output=True, text=True)
        self.assertIn('new alert', r.stdout)
        r = subprocess.run([sys.executable, '-I', os.path.join(SW, 'coord', 'triggers.py'), h, '6'], capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), '')                                 # same trigger set: not again within the hour


if __name__ == '__main__':
    unittest.main()
