# Portable agentq

This package installs the `agentq` GitHub backlog coordinator without the
`dk-devkit` checkout or its `devbox` router.

`agentq` is the trusted coordinator. It reads GitHub issues, controls the
backlog, publishes validated branches, opens pull requests and can merge when
the repository policy permits. It delegates code generation to `agentbox`.
The sandbox that runs the model must not receive GitHub credentials, an SSH
key, or an SSH agent socket.

## Requirements

- Python 3.10 or later
- Git
- GitHub CLI (`gh`), authenticated with permission to read issues and publish branches
- `agentbox` on `PATH`, with a compatible CLI and locally built sandbox images
- an SSH agent when Git pushes use SSH

Install and run `agentq` in the trusted environment that holds the GitHub
authentication and SSH agent. Do not pass those credentials to `agentbox` or
to a sandbox. `agentq doctor` checks the local requirements for one repository.

The package contains the coordinator, its default policy and model tiers, the
sandbox profile catalog, and the secret scanner. It does not contain an agent
runtime or sandbox images. `agentbox` remains a separate dependency.
The coordinator ignores relative `PATH` entries and executables inside the
target repository when it resolves this dependency.

The `agentbox` command must support the `pipeline` options that `agentq` passes,
including `--repo`, `--branch`, `--prompt-file`, `--base`, `--image`, the
iteration and budget limits, and `--check`. Its sandbox profiles must match the
images pinned in this package's `manifests/sandcastle.env`. Its commit identity
must match `Agent <agent@local>` in that file. A different identity needs an
explicit policy change to `requireAgentAuthoredCommits`; that weakens branch
adoption checks.

## Install

Extract this package and run:

```bash
./install.sh
```

The default prefix is `~/.local`. To use another prefix:

```bash
PREFIX="$HOME/.local" ./install.sh
```

Add `~/.local/bin` to `PATH` if needed. The installer updates the package-owned
files under `~/.local/lib/agentq` and links `agentq` under `~/.local/bin`.
Project policy and run state stay in the project and XDG state directories.

## Enroll a project

The project must be a GitHub repository with the four lifecycle labels used by
its policy. In its checkout:

```bash
agentq setup
agentq setup --write-policy
agentq plan
```

Review `.agentqueue.json`. Add the project checks and required GitHub checks.
Keep `autoMerge` false until the merge policy is deliberate. Then start with
one issue:

```bash
agentq run --once
```

See the [full command and policy reference](https://github.com/daniel-kindl/dk-devkit/blob/main/docs/agentq.md).
