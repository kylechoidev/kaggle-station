#!/usr/bin/env bash
# run_tests.sh - offline checks: shellcheck (if installed), bash -n, py_compile, unit tests. No network, no Kaggle.
set -euo pipefail
cd "$(dirname "$0")/.."
fail=0
for f in scripts/*.sh tests/*.sh; do
  bash -n "$f" || { echo "bash -n FAILED: $f"; fail=1; }
done
if command -v shellcheck >/dev/null; then
  shellcheck -x scripts/*.sh tests/*.sh || fail=1
else
  echo "shellcheck not installed: skipped (e.g. 'pipx run --spec shellcheck-py shellcheck' or apt install shellcheck)"
fi
for f in scripts/*.py tests/*.py; do
  python3 -I -c 'import sys; compile(open(sys.argv[1]).read(), sys.argv[1], "exec")' "$f" || { echo "compile FAILED: $f"; fail=1; }
done
python3 -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -v || fail=1
if [ "$fail" = 0 ]; then echo "ALL CHECKS PASSED"; else echo "SOME CHECKS FAILED"; exit 1; fi
