# SECURITY - threat model

A station runs **autonomous agents as root with `Bash` pre-approved**. They hold **your credentials**, in a
**third party's container**, with **unrestricted outbound internet**, and their output comes back to you. Each of
those is a trust boundary.

## Assets and exposure

| Asset | Where during a run | Who can read it | Worst case |
|---|---|---|---|
| Claude token | worker environments; keys dataset | every agent; anyone signed in to the Kaggle account | your subscription is used until you revoke the token |
| Project API key | `/root/.config/project/api_key` (0600); keys dataset | every agent (root); the account | actions on the project service in your name |
| Keys dataset | Kaggle storage, all versions | **anyone signed in to the account**; collaborators; agents in any run that attaches it | all of the above |
| Kaggle session login | env `KAGGLE_*_TOKEN` in every process; the preinstalled CLI works as the owner | every agent | read access and **write access** (MEASURED: `datasets download` and `datasets version` of private datasets of the owner) and maybe delete access (UNVERIFIED) to your kernels and datasets, for the session's lifetime |
| `KAGGLE_JSON` (if you add it) | `/root/.station/kaggle/kaggle.json`; keys dataset | every agent; the account | full API access to the account until expired |
| Control dataset | Kaggle storage | the account; the station | anyone who can write it is giving prompts to agents with root |
| Private kit | `/kaggle/input`, unpacked tree | every agent; Kaggle | redistribution you had no right to make |
| Worker logs | run output | the account | may contain private inputs |

## Threats and mitigations

| # | Threat | Mitigation |
|---|---|---|
| 1 | Prompt injection or agent mistakes (from project files, web pages, control messages) run with root and network | pre-approve only the needed tools (`Bash,Read,Write,Edit,Glob,Grep`; not WebFetch/WebSearch unless needed); put nothing in the container you cannot afford to have exfiltrated; scoped, revocable credentials |
| 2 | Credential leaks through output | never printed, never on argv, never in `/kaggle/working`; `RESULT_EXCLUDE_GLOBS`; grep outputs for token-shaped strings before publishing anything |
| 3 | The session acts on your Kaggle account | a Kaggle account used only for stations, holding nothing you cannot lose; delete the keys dataset after a campaign; `DROP_ENV_PREFIXES` is hygiene, not a boundary |
| 4 | Shared accounts | everyone signed in sees datasets (including keys), versions and outputs. Do not run your token on an account others control. One account, one owner. |
| 5 | Untrusted outputs | review before executing anything; unpack with `tarfile` `filter='data'` into an empty dir; verify every claim with your authoritative check; normal code review before publishing |
| 6 | Data rights | uploading third-party proprietary data (binaries, disassembly, assets) to a dataset puts it on a third party's storage; the data owner decides; this repo contains none |
| 7 | Platform | Kaggle can in principle see the container; its terms apply |
| 8 | Own-server relay (appendix A) | key forced to `rrsync` in one folder (`restrict`), dedicated unprivileged user, one key per run, pinned host key preferred |

## Checklist before pushing

- [ ] Kaggle account controlled by you alone; nothing on it you cannot lose.
- [ ] Credentials only in the separate private keys dataset (or Kaggle Secrets for editor runs), never in the kit or the code.
- [ ] Kit scanned (`pack_kit.sh` refusal), and contains only data the owner approved for a third-party upload.
- [ ] Brief: never print credentials; private inputs stay in the session.
- [ ] `RESULT_GLOBS`, `RESULT_SUFFIXES`, `RESULT_EXCLUDE_GLOBS` reviewed.
- [ ] Control file reset (`station_ctl.sh reset`).

## Checklist after the run

- [ ] Outputs reviewed as untrusted before merging or publishing.
- [ ] Keys dataset deleted at the end of a campaign; Claude token revoked if anything looked odd.
- [ ] `KAGGLE_JSON` expired if you used it; relay key line removed if you used appendix A.
- [ ] Datasets you no longer need deleted.
