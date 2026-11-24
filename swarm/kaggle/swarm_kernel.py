#!/usr/bin/env python3
"""swarm/kaggle/swarm_kernel.py - Kaggle CPU kernel that runs ONE swarm worker for a few hours (rendered per slot).

swarm/kaggle/kaggle_sched.py replaces the CONFIG line below for each slot and pushes the file. Inputs (private
datasets attached to the kernel):
  code dataset:  swarm_code.tgz.bin (swarm/ + hub/providers.json; made by swarm/kaggle/make_code_bundle.sh). The
                 name ends in .bin on purpose: a file named *.tar.gz was not found by name in a session (OBSERVED).
  keys dataset:  one file per credential (scripts/make_keys_dataset.sh); CONFIG["keys"] maps file name -> path.
The session needs INTERNET (the hosted model, the relay, the item pool). Kaggle gives internet only to
phone-verified accounts; without it this kernel stops at once with NO_INTERNET (see docs/12, Kaggle section).
Loop: start swarm/worker.py; every 60 s rsync the worker's folder to the relay (own server) and pull the relay inbox;
a STOP_ALL file in the inbox makes the worker finish its item, release it and exit. Results are copied to
/kaggle/working/out/ at the end (downloadable with `kaggle kernels output`).
"""
import glob, json, os, shutil, subprocess, sys, tarfile, time, urllib.request

CONFIG = {"agent": "K1", "provider": "provider-a", "adapter": "swarm/adapters/pytests_example.py", "worker_args": [], "run_hours": 11.5, "keys": {"PROVIDER_A_KEY": "~/.config/swarm/keys/provider-a"}, "relay": None, "relay_sub": "slot-1"}

ROOT = '/kaggle/working/root'
OUT = '/kaggle/working/out'


def say(msg):
    print('SWARM %s %s' % (time.strftime('%H:%M:%S', time.gmtime()), msg), flush=True)


def find(name):
    hits = glob.glob('/kaggle/input/**/' + name, recursive=True)
    return hits[0] if hits else None


def setup():
    os.makedirs(ROOT, exist_ok=True); os.makedirs(OUT, exist_ok=True)
    b = find('swarm_code.tgz.bin')
    if not b:
        say('FATAL code bundle swarm_code.tgz.bin not found in /kaggle/input'); sys.exit(2)
    with tarfile.open(b) as t:
        for m in t.getmembers():
            if m.name.startswith('/') or '..' in m.name.split('/'):
                say('FATAL unsafe path in bundle: %s' % m.name); sys.exit(2)
        t.extractall(ROOT)
    for fname, dest in CONFIG.get('keys', {}).items():
        src = find(fname)
        if not src:
            say('WARN key file %s not in the keys dataset' % fname); continue
        dest = os.path.expanduser(dest)
        os.makedirs(os.path.dirname(dest), mode=0o700, exist_ok=True)
        shutil.copyfile(src, dest); os.chmod(dest, 0o600)
    say('setup done (keys written: %d)' % len(CONFIG.get('keys', {})))


def internet_ok():
    provs = json.load(open(os.path.join(ROOT, 'hub', 'providers.json')))
    url = provs[CONFIG['provider']]['url'].rstrip('/') + '/models'
    try:
        urllib.request.urlopen(urllib.request.Request(url, method='GET'), timeout=20)
        return True
    except urllib.error.HTTPError:
        return True          # an HTTP answer (even 401) proves the network works
    except Exception as e:
        say('no route to %s: %s' % (url.split('/')[2], e))
        return False


def relay(push=True):
    r = CONFIG.get('relay')
    if not r:
        return
    key = os.path.expanduser(r['key_path'])
    e = ['ssh', '-i', key, '-o', 'StrictHostKeyChecking=accept-new', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20']
    dst = '%s@%s:%s/%s' % (r['user'], r['host'], r['root'].rstrip('/'), CONFIG['relay_sub'])
    wd = os.path.join(ROOT, 'work', 'agents', CONFIG['agent'])
    if push and os.path.isdir(wd):
        subprocess.run(['rsync', '-a', '--timeout=60', '-e', ' '.join(e), wd + '/', dst + '/outbox/'], capture_output=True, timeout=120)
    os.makedirs(ROOT + '/inbox', exist_ok=True)
    subprocess.run(['rsync', '-a', '--timeout=60', '-e', ' '.join(e), dst + '/inbox/', ROOT + '/inbox/'], capture_output=True, timeout=120)
    if os.path.exists(ROOT + '/inbox/STOP_ALL'):
        os.makedirs(wd, exist_ok=True)
        open(os.path.join(wd, 'STOP'), 'w').write('relay STOP_ALL\n')


def main():
    setup()
    if not internet_ok():
        json.dump({'stop': 'NO_INTERNET', 'note': 'phone-verify the Kaggle account to get internet'}, open(OUT + '/status.json', 'w'))
        say('FATAL NO_INTERNET: this account has no internet (phone verification needed); exiting'); sys.exit(3)
    env = dict(os.environ, SWARM_ROOT=ROOT)
    cmd = [sys.executable, '-I', os.path.join(ROOT, 'swarm', 'worker.py'), '--provider', CONFIG['provider'],
           '--providers', os.path.join(ROOT, 'hub', 'providers.json'), '--adapter', os.path.join(ROOT, CONFIG['adapter']),
           '--agent', CONFIG['agent'], '--deadline-min', str(CONFIG['run_hours'] * 60)] + CONFIG.get('worker_args', [])
    p = subprocess.Popen(cmd, cwd=ROOT, env=env)
    say('worker %s started (pid %d)' % (CONFIG['agent'], p.pid))
    hard = time.time() + CONFIG['run_hours'] * 3600 + 1500
    while p.poll() is None:
        time.sleep(60)
        try:
            relay()
        except Exception as e:
            say('relay error: %s' % e)
        if time.time() > hard:
            say('hard deadline: SIGTERM'); p.terminate()
    relay()
    wd = os.path.join(ROOT, 'work')
    shutil.copytree(wd, os.path.join(OUT, 'work'), dirs_exist_ok=True)
    say('done rc %s' % p.returncode)


if __name__ == '__main__':
    main()
