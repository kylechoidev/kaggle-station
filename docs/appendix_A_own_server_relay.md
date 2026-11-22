# Appendix A - optional live relay through a server you own

Skip this unless you already run an always-on Linux server with sshd that is reachable from the internet. It
gives live status and control every `LOOP_S` (MEASURED in the reference run: status reached the server about
1 minute after the workers started; messages reached all 5 workers on consecutive 60 s passes).

## How it works

```
Kaggle session (outbound only)                         <RELAY_USER>@<RELAY_HOST>:~/relay/
  every LOOP_S:
  rsync out/status.json         ----------------->     outbox/status.json
  rsync inbox/station_control.json <--------------     inbox/station_control.json   (you edit this)
```

The kernel uses the same control-file protocol as the dataset route (docs/06). Only the transport differs.

## Server setup (once)

```bash
sudo useradd -m -s /bin/bash <RELAY_USER>                 # dedicated, unprivileged
sudo -u <RELAY_USER> mkdir -p ~<RELAY_USER>/relay/inbox ~<RELAY_USER>/relay/outbox
ssh-keygen -t ed25519 -N '' -C station-relay -f ./station_relay  # on the home computer; one key per run
```

Add one line to `~<RELAY_USER>/.ssh/authorized_keys` (mode 600, directory 700):

```
command="/usr/bin/rrsync /home/<RELAY_USER>/relay",restrict ssh-ed25519 AAAA...public-key... station-relay
```

| Part | Effect |
|---|---|
| `command="/usr/bin/rrsync <dir>"` | the key can only run rsync, confined to `<dir>` (`rrsync` ships with rsync; the path varies by distribution) |
| `restrict` | no shell, no PTY, no port, agent or X11 forwarding |
| `rrsync -ro` / `-wo` | optional: separate read-only and write-only keys |

Test from the home computer:

```bash
rsync -a -e "ssh -i ./station_relay" <RELAY_USER>@<RELAY_HOST>:inbox/ /tmp/relay_test/   # works
ssh -i ./station_relay <RELAY_USER>@<RELAY_HOST> id                                      # must be refused
```

## Kernel settings

| Setting | Value |
|---|---|
| `RELAY_TARGET` | `'<RELAY_USER>@<RELAY_HOST>'` |
| credential `RELAY_SSH_KEY` | the private key file `./station_relay`, added to the keys dataset: `make_keys_dataset.sh ... RELAY_SSH_KEY=./station_relay` |

The kernel writes the key to `/root/.station/relay_key` (0600). It connects with
`ssh -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new` and `rsync --timeout=60`, inside a
180 s subprocess timeout, so a dead server cannot hang the loop. `rsync`, `rrsync` and `ssh` are on the image
(MEASURED).

## Operating it

```bash
# on the server (or scp from home): write the control file
cp ./ctl/station_control.json ~<RELAY_USER>/relay/inbox/station_control.json
# read status
watch -n 60 cat ~<RELAY_USER>/relay/outbox/status.json
```

Edit the control file with `CTL_NO_UPLOAD=1 scripts/station_ctl.sh ...` and copy it to `inbox/`. Clear `inbox/`
before each new run, or the new run applies old orders.

## Hardening

| Measure | Why |
|---|---|
| one key per run; delete its line afterwards | the key sits in the keys dataset and in the session |
| pin the host key instead of `accept-new` (add a `known_hosts` file to the kit and change the ssh options) | trust-on-first-use can be intercepted |
| nothing on the relay host trusts what arrives in `outbox/` | it was written by agents |
| `inbox/` writable only by you | its content becomes prompts to agents with root |
