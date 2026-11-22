"""docs/04 must be the current kernel source: the code blocks concatenate to scripts/station_kernel.py."""
import os
import re
import subprocess
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def rd(p):
    with open(p) as f:
        return f.read()


class DocsSync(unittest.TestCase):
    def test_generator_check(self):
        r = subprocess.run([sys.executable, '-I', os.path.join(ROOT, 'tools', 'gen_kernel_listing.py'), '--check'],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_blocks_equal_source(self):
        doc = rd(os.path.join(ROOT, 'docs', '04_station_kernel.md'))
        listing = doc.split('## Full listing', 1)[1]
        blocks = re.findall(r'```python\n(.*?)\n```', listing, flags=re.S)
        src = rd(os.path.join(ROOT, 'scripts', 'station_kernel.py'))
        self.assertEqual('\n'.join(blocks) + '\n', src)

    def test_relative_links_exist(self):
        for dp, _, fs in os.walk(ROOT):
            for f in fs:
                if not f.endswith('.md'):
                    continue
                p = os.path.join(dp, f)
                for link in re.findall(r'\]\(([^)#:]+)(?:#[^)]*)?\)', rd(p)):
                    self.assertTrue(os.path.exists(os.path.join(dp, link)), '%s -> %s' % (p, link))


if __name__ == '__main__':
    unittest.main()
