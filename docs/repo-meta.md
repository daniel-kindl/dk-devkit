# Repository metadata

`repo-meta` checks or converges a GitHub repository to the canonical "About"
metadata in `manifests/github-metadata.json`: the description, the homepage and
the topics.

It is the sibling of [`repo-labels`](repo-labels.md). Both hold a public
repository setting in a tracked manifest, so that the setting is reviewable in a
pull request, reproducible on another repository, and checkable afterwards.

It is a trusted user-side tool. It uses the existing `gh` login and does not
create, copy, cache, or print another GitHub credential.

## Why the metadata is tracked

The description is the first thing a reader of a public repository sees. Typed
once into the GitHub web form, it has no history, no review and no check: it
drifts away from the repository it describes and nothing says so.

Finding F9 of the [public-release audit](public-release-audit.md) recorded that
the description, the homepage and the topics were all empty. This manifest is
the answer to it, and `repo-meta check` is the proof that the answer still
holds.

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

The command writes the description and the homepage in one `gh repo edit`, then
adds and removes topics in a second one. It re-reads the repository afterwards
and verifies exact convergence.

**Removing a topic removes it from GitHub topic search**, and clearing the
description or the homepage removes text a reader may already have. For that
reason a plan that contains a `REMOVE` or a `CLEAR` requires confirmation. In a
non-interactive environment it refuses unless `--yes` is present:

```bash
repo-meta sync --yes
```

Use `--yes` only after reviewing the plan or an equivalent dry run. A plan that
only adds topics or replaces a non-empty description is not destructive and
needs no confirmation.

## The plan

| Operation | Meaning |
| --- | --- |
| `SET` | The field is written to the manifest value |
| `CLEAR` | The manifest declares the field empty, and GitHub holds a value |
| `ADD` | A manifest topic is missing from the repository |
| `REMOVE` | The repository holds a topic the manifest does not declare |

An empty `homepage` in the manifest is a declaration, not an omission: it states
that no separate website exists, and a homepage added by hand is reported as
drift.

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
  "topics": ["lowercase-with-hyphens"]
}
```

The tool refuses a manifest that GitHub would reject: a description longer than
350 characters or spanning more than one line, a homepage that is not an
`http(s)` URL, more than 20 topics, a duplicate topic, or a topic that is not
lowercase letters, digits and hyphens within 35 characters.

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

Module 8e compiles the command, validates the shipped manifest and runs the
deterministic tests. None of it reaches the network.
