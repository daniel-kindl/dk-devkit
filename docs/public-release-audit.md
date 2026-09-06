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
| Tags | `archive/agentqueue-run-cli`, `archive/pr19head`, both local only (see F7) |
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
| Repository metadata | `gh repo view` | description, topics and homepage are empty; see F9 |

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

**Correction, 2026-09-06.** Both tags are local only. `git ls-remote --refs
origin` answers with `refs/heads/main` and the pull-request refs, and no
`refs/tags/*`. The audit read the tag list from the local checkout, where a tag
stays until it is pushed. Neither tag becomes visible on publication, so this
finding needs no decision from #17. Deleting them locally remains optional and
changes nothing a reader sees.

### F8 — The security policy has no private reporting channel yet

Classification: **remove the gap before publication**, and it can only be closed
at publication time. This is the one open item.

`SECURITY.md` states plainly that no private vulnerability-reporting channel is
documented, rather than inventing one. #16 recorded the same gap.

GitHub's private vulnerability reporting is the obvious channel, and it cannot
be turned on now: the repository is private, and the API answers `404` for
`repos/<owner>/dk-devkit/private-vulnerability-reporting` while it stays
private. The setting exists for public repositories.

So the order is fixed. Enable private vulnerability reporting immediately after
visibility changes, then replace the gap paragraph in `SECURITY.md` with the
real channel. Both steps belong to #17, and this report records them there.

### F9 — Repository metadata is empty

Classification: **safe technical metadata**, with work for #17.

The description, the topics and the homepage are all empty, so none of them can
leak anything. #17 already owns writing them, and it should, because an empty
description is the first thing a reader sees.

**Answered.** `manifests/github-metadata.json` now holds the description, the
homepage and the topics, and `repo-meta` converges the repository to it and
reports drift afterwards. The finding is closed by a tracked, reviewable and
checkable manifest rather than by one entry in a web form. Read
[repo-meta.md](repo-meta.md).

**Correction, 2026-09-06.** This finding read that the wiki, the projects and
the discussions were all off. That is wrong about the wiki. `gh repo view`
answers `hasWikiEnabled: true`, so publication would have exposed an empty wiki
that this report says does not exist. The wiki repository has never been
created, so nothing was written in it and nothing is lost when it goes off.

A sentence in a report cannot hold a setting. The settings are therefore tracked
next to the About fields, where a change is reviewed and a later drift is
caught. `manifests/github-metadata.json` declares the value below for each one,
`repo-meta` converges the repository to it, and gate G6 fails on any drift.

| Setting | Manifest | Why |
| --- | --- | --- |
| `default_branch` | main | Every link, clone and pull request in this repository targets it. |
| `has_issues` | on | The issues are the roadmap, and #8 and #24 are written to be read. |
| `has_wiki` | off | `docs/` is the documentation. A second surface would carry no review and no check. |
| `has_projects` | off | The issue list is the only backlog, and `agentq` reads it. |
| `has_discussions` | off | A discussion nobody watches answers a reader worse than no discussion does. |
| `allow_merge_commit` | off | One pull request becomes one commit on `main`, so the history stays bisectable. |
| `allow_squash_merge` | on | This is that one commit. |
| `allow_rebase_merge` | off | It puts each intermediate agent commit on `main`. |
| `delete_branch_on_merge` | on | A merged `agent/*` or feature branch has no reader left. |

There are no forks. Branch protection cannot be read while the repository is
private, and it becomes available on publication.

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

1. run `bin/publication-gate` on the exact commit it publishes, and read the
   list of tracked files the audit did not cover;
2. change visibility to public;
3. enable GitHub private vulnerability reporting;
4. replace the gap paragraph in `SECURITY.md` with the real channel;
5. record the publication commit, the date, the tested platform and the support
   limitations.

F7 needs no step: its two tags are local only, as the correction there records.

If the gate reports NO-GO on the publication commit, this GO does not carry.
Stop and audit again.

## The publication gate

`bin/publication-gate` runs the mechanical half of step 1 and prints one
verdict. It changes nothing, it does not change repository visibility, and it
does not replace the decision above.

```bash
bin/publication-gate          # run every gate against HEAD
bin/publication-gate --list   # list the gates without running them
bin/publication-gate --quick  # rehearse; skips the two slow gates
```

| Gate | What it proves |
| --- | --- |
| G1 | The working tree is clean, so every gate below reads the commit that publication exposes. |
| G2 | `origin/main` holds that commit. Publication exposes what GitHub holds, not what this checkout holds. |
| G3 | `bin/scan-secrets` is clean on the tracked tree. |
| G4 | `bin/scan-secrets --history` is clean on every blob. |
| G5 | `./verify.sh` passes with no failed check. |
| G6 | `repo-meta check` finds no drift in the About fields or the settings, which is what F9 asks for. |
| G7 | This file records a GO, and the audited commit is an ancestor of the commit to publish. |

G7 is the reason the command exists. The decision above names the commit it was
recorded against. Publication exposes a later commit, and a decision that names
an older one carries nothing by itself. The gate confirms the ancestry, then
prints every tracked file that changed since the audited commit. That is the
part a tool cannot judge, and printing it makes the human re-check bounded
instead of open-ended.

A gate that did not run did not pass. `--quick` therefore reports NO-GO even
when every gate it ran passed, which keeps a rehearsal from reading like a
publication run. Exit status is 0 for GO, 1 for NO-GO, 2 for a usage error and
3 when the checkout cannot be read.

The gate reads the audited commit and the decision out of this file. Recording
a new audit here moves the gate with it; no second copy of either value exists.
