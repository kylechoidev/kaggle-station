"""End-to-end run of station_kernel.main() on this machine with Kaggle replaced by temp dirs and a stub CLI.

Covers: credential file lookup, kit unpack (.tar.zst), setup shell, gate pass, two workers (plain bash, not
Claude Code), a live control document (message + stop_all) fetched through the stub `kaggle datasets download`,
STOP files, status.json, and the results allow-list. Skipped when no zstd decoder module is available.
"""
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def have_zstd():
    for m in ('compression.zstd', 'zstandard'):
        try:
            __import__(m)
            return True
        except ImportError:
            pass
    return False


def rd(p):
    with open(p) as f:
        return f.read()


@unittest.skipUnless(have_zstd() and shutil.which('zstd') and shutil.which('timeout'), 'needs zstd CLI + decoder module')
class EndToEnd(unittest.TestCase):
    def test_full_run(self):
        tmp = tempfile.mkdtemp()
        inp, wd, out, priv, binp = (os.path.join(tmp, x) for x in ('input', 'work', 'out', 'priv', 'bin'))
        for d in (inp + '/datasets/owner/keys', inp + '/datasets/owner/kit', binp):
            os.makedirs(d)
        with open(inp + '/datasets/owner/keys/CLAUDE_CODE_OAUTH_TOKEN', 'w') as f:
            f.write('dummy\n')
        # kit: a gate (reference + checker) and one file that must NOT come back in the results
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w') as tf:
            for name, data in (('gate/reference.json', '{"a": {"status": "ok"}, "b": {"status": "no"}}'),
                               ('tools/gate.sh', 'echo \'{"a": {"status": "ok"}, "b": {"status": "no"}}\'\n'),
                               ('src/target_data.txt', 'private input')):
                ti = tarfile.TarInfo(name)
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data.encode()))
        raw = os.path.join(tmp, 'kit.tar')
        with open(raw, 'wb') as f:
            f.write(buf.getvalue())
        subprocess.run(['zstd', '-q', raw, '-o', inp + '/datasets/owner/kit/kit_base.tar.zst'], check=True)
        # live control document served by the stub CLI
        ctl = os.path.join(tmp, 'station_control.json')
        with open(ctl, 'w') as f:
            json.dump({'schema': 1, 'seq': 2, 'stop_all': True,
                       'messages': [{'id': 'm1', 'to': '*', 'text': 'wrap up'}]}, f)
        with open(binp + '/kaggle', 'w') as f:
            f.write('#!/bin/bash\n[ "$1 $2" = "datasets download" ] || exit 0\n'
                    'while [ $# -gt 0 ]; do [ "$1" = -p ] && cp "%s" "$2/"; shift; done\n' % ctl)
        os.chmod(binp + '/kaggle', 0o755)
        os.environ['PATH'] = binp + ':' + os.environ['PATH']

        spec = importlib.util.spec_from_file_location('station_kernel', os.path.join(HERE, '..', 'scripts', 'station_kernel.py'))
        sk = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sk)
        sk.INPUT_ROOT, sk.WORKDIR, sk.OUT, sk.PRIVATE_DIR = inp, wd, out, priv
        sk.KIT_ARCHIVES = ['kit_base.tar.zst']
        sk.OPTIONAL_CREDENTIALS, sk.FILE_CREDENTIALS = [], {}
        sk.SETUP_SHELL = 'mkdir -p src && echo setup-ok > setup_marker.txt'
        sk.GATE_CMD = 'bash tools/gate.sh > gate/station.json'
        sk.INSTALL_CMD = sk.PROBE_CMD = None
        sk.WORKER_CMD = ['bash', '-c', 'echo running > agents/{NAME}/STATUS.txt; '
                         'while [ ! -f agents/{NAME}/STOP ]; do sleep 0.2; done; '
                         'echo "done after: $(cat agents/{NAME}/INBOX.md | tail -1)" > agents/{NAME}/REPORT.md; '
                         'echo "int f(){return 1;}" > src/{NAME}.cpp']
        sk.WORKERS = {'W1': 'one', 'W2': 'two'}
        sk.WORKER_STAGGER_S, sk.LOOP_S = 0, 1
        sk.CONTROL_DATASET, sk.CONTROL_POLL_S = 'owner/station-control', 1
        sk.STDOUT_PROGRESS_S = 1
        sk.main()

        self.assertIn('gate compared 2 differences 0', rd(out + '/setup.log'))
        st = json.loads(rd(out + '/status.json'))
        self.assertTrue(st['final'] and st['stop_all'])
        self.assertEqual(st['messages_delivered'], ['m1'])
        with tarfile.open(out + '/results.tar.gz') as tf:
            names = sorted(tf.getnames())
            report = tf.extractfile('agents/W1/REPORT.md').read().decode()
        self.assertIn('wrap up', report)
        self.assertIn('src/W1.cpp', names)
        self.assertNotIn('src/target_data.txt', names)
        self.assertFalse(any(n.endswith(('STOP', 'BRIEF.md')) for n in names), names)
        shutil.rmtree(tmp)


if __name__ == '__main__':
    unittest.main()
