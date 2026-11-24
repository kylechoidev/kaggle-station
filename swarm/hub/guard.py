#!/usr/bin/env python3
"""swarm/hub/guard.py NAME - exit 0 only if $SWARM_ROOT/hub/config.json assigns singleton NAME to this host.
Cron wrapper for cron-type singletons:  python3 -I swarm/hub/guard.py my_scheduler && <job>
Fails closed: a missing config or name exits 1, so nothing runs twice."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import host as H
    c = H.conf()
    sys.exit(0 if c['singletons'][sys.argv[1]]['host'] == H.me(c) else 1)
except Exception:
    sys.exit(1)
