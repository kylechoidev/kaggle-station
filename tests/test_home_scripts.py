"""Offline tests of the home-computer scripts with a stub `kaggle` on PATH (records arguments, never uploads)."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

def rd(p):
    with open(p) as f:
        return f.read()


def wr(p, data):
    with open(p, 'w') as f:
        f.write(data)


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
S = os.path.join(ROOT, 'scripts')


class Home(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        bindir = os.path.join(self.tmp, 'bin')
        os.makedirs(bindir)
        self.calls = os.path.join(self.tmp, 'calls.txt')
        stub = os.path.join(bindir, 'kaggle')
        with open(stub, 'w') as f:
            f.write('#!/bin/sh\necho "$@" >> "%s"\n'
                    'case "$*" in "kernels status"*) echo "owner/x has status \\"KernelWorkerStatus.COMPLETE\\"";; esac\n'
                    % self.calls)
        os.chmod(stub, 0o755)
        self.env = dict(os.environ, PATH=bindir + ':' + os.environ['PATH'])

    def run_s(self, *args, env=None, ok=True):
        r = subprocess.run(['bash'] + list(args), capture_output=True, text=True, env=env or self.env, cwd=self.tmp)
        if ok:
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def calls_text(self):
        return rd(self.calls) if os.path.exists(self.calls) else ''

    def test_push_kernel_metadata(self):
        stage = os.path.join(self.tmp, 'stage')
        self.run_s(os.path.join(S, 'push_kernel.sh'), 'owner/my-station', 'owner/kit-base', 'owner/keys-ds',
                   env=dict(self.env, STAGE_DIR=stage))
        m = json.loads(rd(os.path.join(stage, 'kernel-metadata.json')))
        self.assertEqual(m['kernel_type'], 'script')
        self.assertTrue(m['is_private'] and m['enable_internet'])
        self.assertFalse(m['enable_gpu'])
        self.assertEqual(m['dataset_sources'], ['owner/kit-base', 'owner/keys-ds'])
        self.assertEqual(m['title'], 'my-station')
        self.assertIn('kernels push -p', self.calls_text())

    def test_push_kernel_rejects_short_slug(self):
        r = self.run_s(os.path.join(S, 'push_kernel.sh'), 'owner/abc', 'owner/kit', ok=False)
        self.assertNotEqual(r.returncode, 0)

    def test_control_cycle(self):
        d = os.path.join(self.tmp, 'ctl')
        env = dict(self.env, CTL_NO_UPLOAD='1')
        ctl = os.path.join(S, 'station_ctl.sh')
        self.run_s(ctl, 'init-control', 'owner/station-control', d, env=env)
        self.run_s(ctl, 'send', d, 'W1', 'switch', 'to', 'slice', '3', env=env)
        self.run_s(ctl, 'deadline', d, '2026-01-01T18:00:00Z', env=env)
        self.run_s(ctl, 'stop-all', d, 'on', env=env)
        c = json.loads(rd(os.path.join(d, 'station_control.json')))
        self.assertEqual(c['seq'], 4)
        self.assertEqual(c['messages'], [{'id': 'm2', 'to': 'W1', 'text': 'switch to slice 3'}])
        self.assertEqual(c['deadline_utc'], '2026-01-01T18:00:00Z')
        self.assertTrue(c['stop_all'])
        r = self.run_s(ctl, 'deadline', d, '2026-01-01T18:00:00', env=env, ok=False)
        self.assertNotEqual(r.returncode, 0)   # naive time refused at home
        self.run_s(ctl, 'send', d, '*', 'hello', env=self.env)   # with upload -> stub records a version
        self.assertIn('datasets version -p', self.calls_text())

    def test_keys_dataset_staging(self):
        tok = os.path.join(self.tmp, 'tok.txt')
        wr(tok, 'secret-value\r\n')
        r = self.run_s(os.path.join(S, 'make_keys_dataset.sh'), 'owner/station-keys', 'CLAUDE_CODE_OAUTH_TOKEN=' + tok,
                       env=dict(self.env, CTL_NO_UPLOAD='1'))
        self.assertNotIn('secret-value', r.stdout + r.stderr)
        stage = r.stdout.strip().split('staged in ')[1].split(' ')[0]
        self.assertEqual(rd(os.path.join(stage, 'CLAUDE_CODE_OAUTH_TOKEN')), 'secret-value\n')
        self.assertEqual(oct(os.stat(os.path.join(stage, 'CLAUDE_CODE_OAUTH_TOKEN')).st_mode & 0o777), '0o600')
        shutil.rmtree(stage)

    @unittest.skipUnless(shutil.which('zstd'), 'zstd not installed')
    def test_pack_kit_and_refusal(self):
        src = os.path.join(self.tmp, 'kit')
        os.makedirs(os.path.join(src, 'tools'))
        wr(os.path.join(src, 'tools', 'a.txt'), 'a' * 1000)
        ds = os.path.join(self.tmp, 'ds')
        self.run_s(os.path.join(S, 'pack_kit.sh'), src, 'kit_base.tar.zst', ds, '--upload', 'owner/kit-base')
        self.assertTrue(os.path.exists(os.path.join(ds, 'kit_base.tar.zst.sha256')))
        self.assertIn('datasets create -p', self.calls_text())
        wr(os.path.join(src, 'tools', 'api_key'), 'k')
        r = self.run_s(os.path.join(S, 'pack_kit.sh'), src, 'kit2.tar.zst', ds, ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(ds, 'kit2.tar.zst')))


if __name__ == '__main__':
    unittest.main()
