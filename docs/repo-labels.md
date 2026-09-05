# Repository labels

`repo-labels` checks or converges a GitHub repository to the canonical label catalog in `manifests/github-labels.json`.

It is a trusted user-side tool. It uses the existing `gh` login and does not create, copy, cache, or print another GitHub credential.

## Check for drift

From a GitHub repository:

```bash
repo-labels check
```

Or name another repository explicitly:

```bash
repo-labels check --repo owner/name
```

`check` makes no changes. It exits `0` only when the target labels match the manifest exactly. Exit `1` means drift exists and the printed CREATE / UPDATE / DELETE plan describes it.

## Preview a sync

```bash
repo-labels sync --dry-run
repo-labels sync --repo owner/name --dry-run
```

A dry run prints the exact plan and exits without mutation.

## Apply a sync

```bash
repo-labels sync
```

The command creates missing labels and updates configured labels before it deletes anything. It then re-reads the repository and verifies exact convergence.

**Deleting labels removes them from issues and pull requests.** For that reason, a sync that contains DELETE operations requires confirmation. In a non-interactive environment it refuses unless `--yes` is present:

```bash
repo-labels sync --yes
```

Use `--yes` only after reviewing the plan or an equivalent dry run.

## Alternate manifest

```bash
repo-labels check --config path/to/labels.json
repo-labels sync --config path/to/labels.json --dry-run
```

The manifest format is versioned. Version 1 requires an array of unique label names with six-digit hexadecimal colors and explicit descriptions. `group` is optional documentation metadata and does not affect the GitHub label itself.

## Canonical workflow labels

The shipped catalog includes the labels used by the unattended agent workflow:

- `ready-for-agent`
- `agent-in-progress`
- `ready-for-human`
- `agent-failed`
- `wayfinder`

It also includes a bounded general issue taxonomy for bugs, features, refactors, documentation, security, chores, releases, and the existing general `enhancement` category.

## Relationship to agentq

`agentq` consumes workflow labels according to repository policy. It does **not** silently run `repo-labels sync`.

The future `agentq setup` flow may detect label drift and offer this tool explicitly. Installing `repo-labels`, enrolling a repository for `agentq`, and applying a destructive label sync remain separate actions.

## Exit codes

| Code | Meaning |
| ---: | --- |
| `0` | exact check, successful dry run, or successful sync |
| `1` | `check` found drift |
| `2` | invalid command/configuration |
| `3` | `gh` is unavailable or a GitHub operation failed |
| `4` | destructive sync was refused because confirmation was missing |
| `5` | mutation finished but verification still found drift |
