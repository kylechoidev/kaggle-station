"""Offline tests of station_kernel.py logic: control protocol, stop files, credentials, results allow-list."""
import datetime as dt
import importlib.util
import json
import os
import sys
import tarfile
import tempfile
import time
import unittest

def rd(p):
    with open(p) as f:
        return f.read()


def wr(p, data):
    with open(p, 'w') as f:
        f.write(data)


HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('station_kernel', os.path.join(HERE, '..', 'scripts', 'station_kernel.py'))
sk = importlib.util.module_from_spec(spec)
sys.modules['station_kernel'] = sk
spec.loader.exec_module(sk)   # module name 'station_kernel': main() does not run

UTC = dt.timezone.utc
T0 = dt.datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def fresh_state():
    return {'start': T0, 'cap': T0 + dt.timedelta(hours=11), 'deadline': T0 + dt.timedelta(hours=3),
            'soft_stop': T0 + dt.timedelta(hours=3, minutes=-20), 'stop_all': False, 'control_seq': -1,
            'delivered': set(), 'soft_stopped': False, 'log': None}


class ControlProtocol(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.agents = os.path.join(self.tmp, 'agents')
        self.st = fresh_state()
        self.w = ['W1', 'W2']

    def inbox(self, w):
        p = os.path.join(self.agents, w, 'INBOX.md')
        return rd(p) if os.path.exists(p) else ''

    def test_message_delivered_once_by_id(self):
        ctl = {'seq': 1, 'messages': [{'id': 'm1', 'to': 'W1', 'text': 'hello'}]}
        sk.apply_control(ctl, self.st, self.agents, self.w, T0)
        ctl2 = {'seq': 2, 'messages': [{'id': 'm1', 'to': 'W1', 'text': 'hello'},
                                       {'id': 'm2', 'to': '*', 'text': 'all'}]}
        sk.apply_control(ctl2, self.st, self.agents, self.w, T0)
        self.assertEqual(self.inbox('W1').count('hello'), 1)
        self.assertIn('all', self.inbox('W1'))
        self.assertIn('all', self.inbox('W2'))
        self.assertNotIn('hello', self.inbox('W2'))

    def test_stale_seq_ignored(self):
        sk.apply_control({'seq': 5, 'deadline_utc': '2026-01-01T14:00:00Z'}, self.st, self.agents, self.w, T0)
        acts = sk.apply_control({'seq': 5, 'deadline_utc': '2026-01-01T13:00:00Z'}, self.st, self.agents, self.w, T0)
        self.assertEqual(acts, [])
        self.assertEqual(self.st['deadline'], dt.datetime(2026, 1, 1, 14, 0, tzinfo=UTC))

    def test_deadline_capped_and_soft_stop_follows(self):
        sk.apply_control({'seq': 1, 'deadline_utc': '2026-01-03T00:00:00Z'}, self.st, self.agents, self.w, T0)
        self.assertEqual(self.st['deadline'], self.st['cap'])
        self.assertEqual(self.st['soft_stop'], self.st['cap'] - dt.timedelta(minutes=sk.SOFT_STOP_LEAD_MIN))

    def test_soft_stop_capped_at_deadline(self):
        sk.apply_control({'seq': 1, 'soft_stop_utc': '2026-01-02T00:00:00Z'}, self.st, self.agents, self.w, T0)
        self.assertEqual(self.st['soft_stop'], self.st['deadline'])

    def test_stop_all_then_lift(self):
        sk.apply_control({'seq': 1, 'stop_all': True}, self.st, self.agents, self.w, T0)
        self.assertTrue(sk.soft_stop_due(self.st, T0))
        sk.write_stop_files(self.agents, self.w, 'stop_all')
        self.st['soft_stopped'] = True
        sk.apply_control({'seq': 2, 'stop_all': False}, self.st, self.agents, self.w, T0)
        self.assertFalse(os.path.exists(os.path.join(self.agents, 'W1', 'STOP')))
        self.assertFalse(sk.soft_stop_due(self.st, T0))

    def test_operator_stop_file_not_lifted(self):
        os.makedirs(os.path.join(self.agents, 'W1'))
        wr(os.path.join(self.agents, 'W1', 'STOP'), 'written by the agent itself\n')
        self.st['soft_stopped'] = True
        sk.apply_control({'seq': 1, 'stop_all': False}, self.st, self.agents, self.w, T0)
        self.assertTrue(os.path.exists(os.path.join(self.agents, 'W1', 'STOP')))

    def test_naive_time_is_utc(self):
        self.assertEqual(sk.parse_utc('2026-01-01T13:00:00'), dt.datetime(2026, 1, 1, 13, tzinfo=UTC))

    def test_control_file_plain_and_zipped(self):
        import zipfile
        p = os.path.join(self.tmp, sk.CONTROL_FILE)
        wr(p, json.dumps({'seq': 3}))
        self.assertEqual(sk.read_control_file(p)['seq'], 3)
        z = os.path.join(self.tmp, 'c.zip')
        with zipfile.ZipFile(z, 'w') as zf:
            zf.write(p, sk.CONTROL_FILE)
        self.assertEqual(sk.read_control_file(z)['seq'], 3)
        self.assertIsNone(sk.read_control_file(os.path.join(self.tmp, 'missing.json')))


class Credentials(unittest.TestCase):
    def test_file_lookup_by_name_any_depth(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, 'datasets', 'owner', 'keys'))
        wr(os.path.join(root, 'datasets', 'owner', 'keys', 'MY_TOKEN'), 'abc\n')
        self.assertEqual(sk.credential('MY_TOKEN', root=root), 'abc')
        self.assertIsNone(sk.credential('ABSENT', required=False, root=root))


class Results(unittest.TestCase):
    def test_allow_list(self):
        wd = tempfile.mkdtemp()
        os.makedirs(os.path.join(wd, 'agents', 'W1'))
        os.makedirs(os.path.join(wd, 'toolchain'))
        os.makedirs(os.path.join(wd, 'src'))

        def put(rel, data='x'):
            with open(os.path.join(wd, rel), 'w') as f:
                f.write(data)
        put('src/kit_file.cpp', 'from the kit')
        put('toolchain/compiler.txt')
        kit = sk.manifest(wd)
        time.sleep(0.01)
        put('src/new.cpp')
        put('agents/W1/REPORT.md')
        put('agents/W1/STOP')
        put('agents/W1/api_key.txt')
        put('agents/W1/target.bin')
        put('agents/W1/huge.txt', 'y' * (sk.RESULT_MAX_FILE_BYTES + 1))
        os.symlink(os.path.join(wd, 'toolchain', 'compiler.txt'), os.path.join(wd, 'agents', 'W1', 'link.txt'))
        got = sorted(sk.select_results(wd, kit))
        self.assertEqual(got, ['agents/W1/REPORT.md', 'src/new.cpp'])
        put('src/kit_file.cpp', 'edited by a worker')
        self.assertIn('src/kit_file.cpp', sk.select_results(wd, kit))
        dest = os.path.join(wd, 'results.tar.gz')
        sk.pack_results(wd, kit, dest)
        with tarfile.open(dest) as tf:
            self.assertEqual(sorted(tf.getnames()), ['agents/W1/REPORT.md', 'src/kit_file.cpp', 'src/new.cpp'])

    def test_fill_tokens(self):
        cmd = [sk.fill(x, 'W1', 'slice 1', 'BRIEF TEXT', '/b.md') for x in ['run', '{NAME}', '{BRIEF}', '{BRIEF_FILE}', '{ASSIGNMENT}']]
        self.assertEqual(cmd, ['run', 'W1', 'BRIEF TEXT', '/b.md', 'slice 1'])


if __name__ == '__main__':
    unittest.main()
