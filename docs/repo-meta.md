# Repository metadata

`repo-meta` checks or converges a GitHub repository to
`manifests/github-metadata.json`. The manifest holds the "About" metadata a
reader sees, which is the description, the homepage and the topics, and the
repository settings, which are the default branch, the surfaces that exist and
the merge methods.

It is the sibling of [`repo-labels`](repo-labels.md). Both hold a public
repository setting in a tracked manifest, so that the setting is reviewable in a
pull request, reproducible on another repository, and checkable afterwards.

It is a trusted user-side tool. It uses the existing `gh` login and does not
create, copy, cache, or print another GitHub credential.

## Install

```bash
./install.sh --components repo-meta
```

The component links `bin/repo-meta` into `~/.local/bin`, so a normal shell
resolves `repo-meta`. It needs the GitHub CLI, which it declares as the `gh`
capability: a machine without `gh` is reported before the installation, not at
the first command.

The installation is idempotent, and readiness is a fact about the installed
command. Deleting `~/.local/bin/repo-meta` and running the installation again
restores it. Authentication stays a manual step: `gh auth login` where you run
the command.

## Why the metadata is tracked

The description is the first thing a reader of a public repository sees. Typed
once into the GitHub web form, it has no history, no review and no check: it
drifts away from the repository it describes and nothing says so.

Finding F9 of the [public-release audit](public-release-audit.md) recorded that
the description, the homepage and the topics were all empty. This manifest is
the answer to it, and `repo-meta check` is the proof that the answer still
holds.

The same finding recorded the settings in a sentence, and the sentence was wrong
about the wiki: it said off, and GitHub answered on. A setting a report only
describes is a setting nothing checks. The settings are therefore in the
manifest as well, and F9 now holds the table that `verify.sh` module 8e compares
against it.

## Check for drift

From a GitHub repository:

```bash
repo-meta check
```

Or name another repository explicitly:

```bash
repo-meta check --repo owner/name
```

`check` makes no changes. It exits `0` only when the target metadata matches the
manifest exactly. Exit `1` means drift exists and the printed plan describes it.

## Preview a sync

```bash
repo-meta sync --dry-run
repo-meta sync --repo owner/name --dry-run
```

A dry run prints the exact plan and exits without mutation.

## Apply a sync

```bash
repo-meta sync
```

The command writes the description and the homepage in one `gh repo edit`, adds
and removes topics in a second one, and writes the settings in a third. Each
edit is separate, so a failure names the half that failed. It re-reads the
repository afterwards and verifies exact convergence.

**Removing a topic removes it from GitHub topic search**, and clearing the
description or the homepage removes text a reader may already have.
**Turning a surface off** hides it and the content in it, and **retargeting the
default branch** moves where every new clone and every new pull request lands.
For that reason a plan that contains a `REMOVE`, a `CLEAR`, a `DISABLE` or a
`RETARGET` requires confirmation. In a non-interactive environment it refuses unless
`--yes` is present:

```bash
repo-meta sync --yes
```

Use `--yes` only after reviewing the plan or an equivalent dry run. A plan that
only adds topics or replaces a non-empty description is not destructive and
needs no confirmation.

The plan goes to stdout and every message about it goes to stderr, and the plan
always comes first. That holds when the two streams are joined, which is what a
pipe, a log and a shell capture all do: stdout is block-buffered away from a
terminal, so the command flushes it before it writes to stderr. Without that,
`refused destructive sync` arrives before the plan it refuses.

## The plan

| Operation | Meaning | Destructive |
| --- | --- | --- |
| `SET` | The field is written to the manifest value | no |
| `CLEAR` | The manifest declares the field empty, and GitHub holds a value | yes |
| `ADD` | A manifest topic is missing from the repository | no |
| `REMOVE` | The repository holds a topic the manifest does not declare | yes |
| `ENABLE` | The manifest declares a setting on, and GitHub holds it off | no |
| `DISABLE` | The manifest declares a setting off, and GitHub holds it on | yes |
| `RETARGET` | The repository points at another default branch | yes |
| `UNKNOWN` | The manifest declares a setting `gh` did not report | reported, never written |

An empty `homepage` in the manifest is a declaration, not an omission: it states
that no separate website exists, and a homepage added by hand is reported as
drift.

An `UNKNOWN` is drift this side cannot repair. A `gh` that does not report a
setting leaves this command with no reading of what a write would replace, so it
reports the setting and writes nothing.

## The settings

The `settings` block is optional, and it manages exactly the settings it names.
A setting the manifest omits is not compared and not written, so a repository
keeps a setting this manifest does not own. A key outside the table below is a
manifest error, because a silent typo would read as an unmanaged setting.

| Key | GitHub setting |
| --- | --- |
| `default_branch` | The default branch |
| `has_issues` | Issues |
| `has_wiki` | Wiki |
| `has_projects` | Projects |
| `has_discussions` | Discussions |
| `allow_merge_commit` | Merge commits |
| `allow_squash_merge` | Squash merging |
| `allow_rebase_merge` | Rebase merging |
| `delete_branch_on_merge` | Delete the head branch on merge |

Every value except `default_branch` is `true` or `false`. A number and a string
are refused, because `1` is not `true` to a reader. `default_branch` is a branch
name of letters, digits, `.`, `_`, `-` or `/` that starts with a letter or a
digit.

GitHub needs at least one merge method. A manifest that declares all three off
is refused here, where the message says so, instead of failing inside `gh`.

## Alternate manifest

```bash
repo-meta check --config path/to/metadata.json
```

The manifest is a single JSON object:

```json
{
  "version": 1,
  "description": "one line, at most 350 characters",
  "homepage": "",
  "topics": ["lowercase-with-hyphens"],
  "settings": {
    "default_branch": "main",
    "has_wiki": false
  }
}
```

The tool refuses a manifest that GitHub would reject: a description longer than
350 characters or spanning more than one line, a homepage that is not an
`http(s)` URL, more than 20 topics, a duplicate topic, a topic that is not
lowercase letters, digits and hyphens within 35 characters, an unmanaged
settings key, a toggle that is not `true` or `false`, an invalid branch name, or
every merge method off.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Metadata matches the manifest, or a dry run completed |
| `1` | Drift exists (`check`) |
| `2` | Usage or manifest error |
| `3` | `gh` failed, or is absent |
| `4` | A destructive sync was refused |
| `5` | The repository still differs after a sync |

## Verification

```bash
./verify.sh --only 87
```

Module 8e compiles the command, validates the shipped manifest, runs the
deterministic tests and compares the manifest settings against the F9 table of
the [public-release audit](public-release-audit.md). It also proves that the
`repo-meta` command is installed on the host and that a host login shell
resolves it. None of it reaches the network.

Gate G6 of `bin/publication-gate` runs `repo-meta check` against the live
repository, so drift in a setting stops publication.
