#!/usr/bin/env python3
"""swarm/hub/self_update.py - keep this host's verifier/toolchain on the published version, with recheck and rollback.

Config "self_update" in $SWARM_ROOT/hub/config.json (all commands run with cwd = $SWARM_ROOT, shell):
  "published_cmd": prints the published version id (e.g. a hash from a status endpoint, a release tag)
  "install_dir":   the live verifier folder (relative to SWARM_ROOT), e.g. "verifier/current"
  "version_file":  file inside install_dir holding the installed version id, e.g. "VERSION"
  "fetch_cmd":     downloads AND verifies the new version into {dest} (an empty folder); exit 0 = ok
  "recheck_cmd":   re-checks a sample of past accepted results with the verifier in install_dir; exit 0 = pass
  "every_min":     how often host.py runs this (default 10)
Flow on a difference: create work/flags/VERIFIER_STALE (workers hold) -> fetch into install_dir.new_<UTC> -> rename the
live folder to install_dir.old_<UTC> -> swap -> recheck. Pass: write the version, remove the flag. Fail: swap back,
keep the flag with the reason, write an alert, exit 3. Exit 0 current/installed, 1 published version unknown or fetch
failed (nothing changed), 3 rolled back.
"""
import datetime as dt, json, os, shutil, subprocess, sys

ROOT = os.path.abspath(os.environ.get('SWARM_ROOT', '.'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import host as H  # noqa: E402


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True, timeout=3600, **kw)


def main():
    cfg = H.conf().get('self_update') or {}
    if not cfg:
        print('no self_update config'); return 0
    flag = os.path.join(ROOT, 'work', 'flags', 'VERIFIER_STALE')
    os.makedirs(os.path.dirname(flag), exist_ok=True)
    live = os.path.join(ROOT, cfg['install_dir'])
    vf = os.path.join(live, cfg.get('version_file', 'VERSION'))
    r = sh(cfg['published_cmd'])
    pub = r.stdout.strip().splitlines()[-1].strip() if r.returncode == 0 and r.stdout.strip() else None
    if not pub:
        print('published version unknown: %s' % (r.stderr.strip()[-200:])); return 1
    cur = open(vf).read().strip() if os.path.exists(vf) else None
    if cur == pub:
        if os.path.exists(flag) and open(flag).read().startswith('self_update: installing'):
            os.remove(flag)
        print('current %s' % pub[:16]); return 0
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    with open(flag, 'w') as f:
        f.write('self_update: installing %s (local %s) %s\n' % (pub[:16], (cur or '-')[:16], stamp))
    new = '%s.new_%s' % (live, stamp)
    os.makedirs(new)
    r = sh(cfg['fetch_cmd'].replace('{dest}', new))
    if r.returncode:
        shutil.rmtree(new, ignore_errors=True)
        H.alert('self_update: fetch of %s failed: %s' % (pub[:16], (r.stdout + r.stderr).strip()[-200:]))
        return 1
    old = '%s.old_%s' % (live, stamp)
    if os.path.exists(live):
        os.rename(live, old)
    os.rename(new, live)
    r = sh(cfg['recheck_cmd'])
    if r.returncode:
        os.rename(live, '%s.failed_%s' % (live, stamp))
        if os.path.exists(old):
            os.rename(old, live)
        with open(flag, 'w') as f:
            f.write('self_update: version %s failed the recheck; old version restored; held for a human.\n%s\n' % (
                pub[:16], (r.stdout + r.stderr).strip()[-1500:]))
        H.alert('self_update: %s failed the recheck; rolled back; VERIFIER_STALE kept' % pub[:16])
        return 3
    with open(vf, 'w') as f:
        f.write(pub + '\n')
    os.remove(flag)
    with open(os.path.join(ROOT, 'hub', 'log', 'self_update.log'), 'a') as f:
        f.write('%s installed %s\n' % (stamp, pub))
    print('installed %s' % pub[:16]); return 0


if __name__ == '__main__':
    sys.exit(main())
