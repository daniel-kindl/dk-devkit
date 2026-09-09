# Repository labels

`repo-labels` checks or converges a GitHub repository to the canonical label catalog in `manifests/github-labels.json`.

It is a trusted user-side tool. It uses the existing `gh` login and does not create, copy, cache, or print another GitHub credential.

## Install

```bash
./install.sh --components repo-labels
```

The component links `bin/repo-labels` into `~/.local/bin`, so a normal shell
resolves `repo-labels`. It needs the GitHub CLI, which it declares as the `gh`
capability: a machine without `gh` is reported before the installation, not at
the first command.

The installation is idempotent, and readiness is a fact about the installed
command. Deleting `~/.local/bin/repo-labels` and running the installation again
restores it.

```bash
./install.sh --state --components repo-labels    # what it owns and what it writes
```

Authentication stays a manual step: `gh auth login` where you run the command.

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

## The canonical catalog

The shipped catalog is bounded. It names the labels that are useful to the repositories and the workflows tracked here. It does not keep the GitHub default labels, and it does not add a category only for completeness.

`group` divides the catalog into five parts. Colors may be shared where an external workflow defines the label palette.

### `type` - what kind of work an issue is

| Label | Meaning |
| --- | --- |
| `bug` | Something is not working |
| `feature` | New user-visible capability |
| `enhancement` | General improvement that does not fit a more specific type |
| `refactor` | Structural change without intended behavior change |
| `documentation` | Documentation-only work |
| `security` | Security-sensitive work |
| `chore` | Maintenance and tooling work |
| `release` | Release and publication work |
| `research` | Investigation or evaluation intended to produce evidence, findings, or a recommendation |
| `design` | Architecture, API, workflow, interface, or system design work |
| `verification` | Verification gates, probes, self-tests, validation, or support evidence |
| `performance` | Performance, efficiency, startup time, or resource-usage work |
| `dependencies` | Dependency, runtime, toolchain, or pinned-version changes |
| `platform-support` | Platform compatibility, capability adapters, or support-tier work |

`enhancement` is the fallback. Use a more specific type when one applies.

### `agent-workflow` - the unattended agent lifecycle

| Label | Meaning |
| --- | --- |
| `ready-for-agent` | Specified and eligible for unattended agent work |
| `agent-in-progress` | Currently claimed by the unattended agent workflow |
| `ready-for-human` | Requires human decision, review, or intervention |
| `agent-failed` | Unattended agent execution reached an issue-local terminal failure |
| `wayfinder` | Issue participates in the Wayfinder discovery/specification workflow |

`agentq` depends on this group. `lib/agentqueue/setup.py` reads the same file and selects the labels whose group is `agent-workflow`, so the catalog stays the one source of truth.

### `wayfinder` - how a Wayfinder ticket is resolved

| Label | Color | Meaning |
| --- | --- | --- |
| `wayfinder:grilling` | `#d876e3` | A wayfinder ticket resolved by conversation with the maintainer. |
| `wayfinder:map` | `#5319e7` | A wayfinder map issue. It indexes the decisions of one effort. |
| `wayfinder:prototype` | `#a2eeef` | A wayfinder ticket resolved by a throwaway prototype. |
| `wayfinder:research` | `#0075ca` | A wayfinder ticket resolved by reading primary sources. |
| `wayfinder:task` | `#fbca04` | A wayfinder ticket resolved by manual work that unblocks a decision. |

### `impact` - what a change costs a consumer

| Label | Meaning |
| --- | --- |
| `breaking-change` | Intentionally changes a public or compatibility-sensitive contract |

### `status` - why an issue is not moving

| Label | Meaning |
| --- | --- |
| `blocked` | Cannot progress until a dependency, decision, issue, or external condition is resolved |

A `type` label is expected on every issue. A label from `impact` or `status` is added only when it applies, and more than one group can apply at the same time.

## Relationship to agentq

`agentq` consumes workflow labels according to repository policy. It does **not** silently run `repo-labels sync`.

`agentq setup` detects label drift and names the command that repairs it. It never runs the sync itself. Installing `repo-labels`, enrolling a repository for `agentq`, and applying a destructive label sync are three separate actions, and the third one is a human decision.

## Verification

```bash
./verify.sh --only 86
```

Module 8d compiles the command and checks that the shipped manifest is valid
JSON. It runs the deterministic tests. It proves that the `repo-labels` command
is installed on the host and that a host login shell resolves it, which is the
check the command was missing when a documented `repo-labels check` answered
`command not found`. It also reads this document for the sentence that states
what a destructive sync costs. None of it reaches the network, and none of it
needs a GitHub credential.

## Exit codes

| Code | Meaning |
| ---: | --- |
| `0` | exact check, successful dry run, or successful sync |
| `1` | `check` found drift |
| `2` | invalid command/configuration |
| `3` | `gh` is unavailable or a GitHub operation failed |
| `4` | destructive sync was refused because confirmation was missing |
| `5` | mutation finished but verification still found drift |
