# Public-release audit

This is the deliberate public-readiness review that must happen before this
repository changes from private to public. It is a release gate, not a routine
secret scan: a clean scan proves that no credential is present, and publication
also exposes identity, machine facts, history, issues and pull requests.

Issue #15 owns this report. Issue #17 owns publication, and it must not start
until the decision at the end of this file says GO.

## What was audited

| | |
| --- | --- |
| Audited commit | `ce6e834fde94b1101e12e8945543e2e8757beee1` |
| Commit date | 2026-09-06 |
| Audit date | 2026-09-06 |
| Tracked files | 169 |
| Commits, all refs | 33 |
| Blobs in history | 431 |
| Branches | `main` only |
| Tags | `archive/agentqueue-run-cli`, `archive/pr19head` |
| Issues | 18 (13 closed, 5 open) |
| Pull requests | 20, all merged |

The audit ran on the Bazzite host toolkit inside the `web-dev` container, which
is the machine this repository describes. That matters: several findings below
are about that machine, and they were read from it rather than guessed.

## Method and evidence

| Check | Command | Result |
| --- | --- | --- |
| Tracked and staged secret scan | `bin/scan-secrets` | clean, 169 files, 0 findings |
| Whole-history secret scan | `bin/scan-secrets --history` | clean, 431 blobs, 0 findings |
| Issue and pull-request text | `bin/scan-secrets --stdin` over every body, comment and review | clean, 0 findings |
| Full verification | `./verify.sh` | 609 passed, 0 failed, 0 skipped |
| Full verification, with this report | `./verify.sh` | 611 passed, 0 failed, 0 skipped |
| Identity in history | `git log --all --format='%an <%ae>'` | two addresses, both already public |
| Machine paths in the tree | `git grep` for `/home/`, `/var/home/`, `/Users/` | no path names this machine |
| Machine paths in history | `git log --all -S` | two commits, see below |
| Other repositories named | `git grep` against the account's repository list | only public repositories |
| Actions history | `gh run list` | GitHub dependency-graph runs only; the repository tracks no workflow |
| Repository metadata | `gh repo view` | description, topics and homepage are empty |

The two extra checks are this report and the guard in F2. Everything else
is identical on both commits.

The secret scan alone is not the audit. Everything below is the part a scanner
cannot decide.

## Findings

Each finding carries one of the five classifications that #15 requires:
**intentionally public**, **safe technical metadata**, **parameterize**,
**move to local state**, or **remove before publication**.

### F1 — Two author addresses become public

Classification: **intentionally public**. No action.

The history carries `daniel.kindl@proton.me` on 20 commits and
`git@danielkindl.dev` on 13. Publication cannot hide either one, and a history
rewrite would be the only way to change them.

Neither is a new disclosure. Both addresses already appear as the commit author
in repositories this account has already published, so publishing this
repository reveals nothing that a reader cannot read today.

### F2 — The host account name survives in history

Classification: **parameterize**, done in the tree; **intentionally public** for
history. No further action.

The tracked tree named one machine's home directory until the public and local
state boundary landed in #38. `bin/devbox-verify` now derives both spellings of
the home directory from the environment, and the two documentation examples use
`<user>`, `$HOME` or `~/`. No tracked file names this machine today.

Two historical commits still carry the account name inside a path, for example
`/home/<user>/projects/...`:

- `4d471a3` Define the Bazzite workstation as version-controlled configuration
- `9df6a5c` feat: add unattended agent orchestration with Sandcastle

Removing them needs a history rewrite. The value is a local operating-system
account name. It grants no access, it is not a credential, and it is the same
class of fact as a home-directory path in any screenshot. A history rewrite
costs every commit hash in the repository and every link that points at one, so
the trade is not worth it for this value.

`verify.sh` module 7 now fails if a new tracked file names the running machine's
home directory. The guard derives the path at run time, so it names no account
in the repository and it works on any machine.

### F3 — Commit messages link to agent session records

Classification: **safe technical metadata**. No action.

Forty-one commit messages carry a `Claude-Session:` trailer that points at a
`claude.ai/code/session_...` URL. Those URLs become public with the repository.

One unauthenticated request to such a URL answered `403`, so the link does not
open the session for a reader who is not signed in as the owner. The trailer is
therefore a provenance record, not a way in. It stays.

### F4 — Every other repository named here is already public

Classification: **safe technical metadata**. No action.

Documentation and tests use `dkkb` as the worked example, including
`daniel-kindl/dkkb` in two places. That repository is public. No private
repository of this account is named anywhere in the tree, in the history, or in
the issue and pull-request text.

The word "dotfiles" appears three times as an ordinary noun about container home
directories. It does not refer to the private repository of that name.

### F5 — Test fixtures use invented identities

Classification: **safe technical metadata**. No action.

The probes use `person@example.invalid`, `human@example.invalid`,
`Mallory <m@example.invalid>` and synthetic paths such as `/home/daniel/...`,
`/Users/daniel/x` and `/home/x/...`. `.invalid` cannot resolve, and none of the
paths is this machine's home directory.

### F6 — Personal software preferences are tracked on purpose

Classification: **intentionally public**. No action.

`manifests/flatpaks.txt` and `manifests/homebrew.txt` record which applications
this workstation installs, and `manifests/skills.tsv` records 61 third-party
agent skills with their source repository and ref. These reveal preferences: a
password manager, a browser, a mail client, an editor.

That is the point of the `daniel` profile, and #24 states it: the profile may be
opinionated and public. `components/daniel/component.json` holds no credential
and no machine identity, and `./install.sh --state` reports the boundary for
every component.

### F7 — Two archive tags become visible

Classification: **safe technical metadata**, with a decision for #17.

`archive/agentqueue-run-cli` and `archive/pr19head` are not ancestors of `main`.
They preserve two development branches. Both are inside the history scan, which
is clean, and neither holds a credential.

They are development evidence with no value to a reader. #17 may delete them
before publication or keep them. Either choice is safe. Publication does not
depend on it.

### F8 — The security policy has no private reporting channel yet

Classification: **remove the gap before publication**, and it can only be closed
at publication time. This is the one open item.

`SECURITY.md` states plainly that no private vulnerability-reporting channel is
documented, rather than inventing one. #16 recorded the same gap.

GitHub's private vulnerability reporting is the obvious channel, and it cannot
be turned on now: the repository is private, and the API answers `404` for
`repos/<owner>/workstation/private-vulnerability-reporting` while it stays
private. The setting exists for public repositories.

So the order is fixed. Enable private vulnerability reporting immediately after
visibility changes, then replace the gap paragraph in `SECURITY.md` with the
real channel. Both steps belong to #17, and this report records them there.

### F9 — Repository metadata is empty

Classification: **safe technical metadata**, with work for #17.

The description, the topics and the homepage are all empty, so none of them can
leak anything. #17 already owns writing them, and it should, because an empty
description is the first thing a reader sees.

Issues are enabled. The wiki, projects and discussions are off. The default
branch is `main`. There are no forks. Branch protection cannot be read while the
repository is private, and it becomes available on publication.

### F10 — Issues, pull requests and Actions hold nothing to redact

Classification: **safe technical metadata**. No action.

Every issue and pull request was written by the repository owner. The combined
text of 18 issues and 20 pull requests, with their comments and reviews, scans
clean. It names no private repository and no email address other than the
Anthropic no-reply co-author address.

One pull-request description mentions the host account name once, while
describing the remediation in F2. The exposure is the same as F2 and the same
judgement applies.

The repository tracks no GitHub Actions workflow. The only runs in the account's
history for this repository are GitHub's own dependency-graph updates, which
produce no artifact and no log that a reader could mine.

## Intentionally public personal information

A reader of the public repository learns:

- the owner's name, and the two commit-author addresses in F1;
- which desktop applications, command-line tools and agent skills this
  workstation installs;
- that the primary machine runs Bazzite, and the shape of its home directory;
- the owner's development habits, in detail, through the documentation.

All of it is deliberate. The `daniel` profile is a public composition, and the
documentation is honest about the machine it describes because that is what
makes it useful.

## Residual limitations

These are limits of the audit, not defects to fix before publication:

- Bazzite is the only platform with verification evidence. The README, the
  component documentation and `docs/platforms.md` already say so, and the
  support claim must not grow past the evidence.
- Part of `verify.sh` needs this host and this container, so a contributor
  cannot run all 609 checks. `CONTRIBUTING.md` says that a pull request must
  state which checks it could not run.
- The audit reads the repository, its history, its issues and its pull requests.
  It cannot review a private note, a local branch, or anything that never
  reached this remote.

## Decision

**GO**, subject to the two publication-time steps in F8.

Every gate #15 defines is met on `ce6e834`:

- the tracked-tree scan is clean;
- the whole-history scan is clean;
- full verification passes with 0 failures;
- the tree, the history, the issues, the pull requests, the tags and the Actions
  history were reviewed for material that a scanner does not catch;
- every personal or machine-specific value found is classified above;
- the one required remediation, F2, is already in the tree, and a verification
  check now keeps it there.

#17 must, in this order:

1. re-run `bin/scan-secrets`, `bin/scan-secrets --history` and `./verify.sh` on
   the exact commit it publishes;
2. decide on the two archive tags in F7;
3. write the repository description and topics from F9;
4. change visibility to public;
5. enable GitHub private vulnerability reporting;
6. replace the gap paragraph in `SECURITY.md` with the real channel;
7. record the publication commit, the date, the tested platform and the support
   limitations.

If any step 1 check fails on the publication commit, this GO does not carry.
Stop and audit again.
