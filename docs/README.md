# Documentation

The toolkit is the product. Daniel's complete workstation is one profile of the
same components, so the groups below are separate.

Start at the [project README](../README.md). [CONTRIBUTING.md](../CONTRIBUTING.md)
states the change policy, and [SECURITY.md](../SECURITY.md) states the security
policy and the trust boundaries.

## The toolkit

| Document | What it covers |
| --- | --- |
| [components.md](components.md) | The component contract, the installer, the profiles, and the public/local state boundary |
| [platforms.md](platforms.md) | The capability contract, the platform adapters, and what each support tier claims |
| [environments.md](environments.md) | The development environment module, and the environments that exist today |
| [not-tracked.md](not-tracked.md) | What stays outside Git, and where each excluded thing lives instead |
| [secrets.md](secrets.md) | The credential policy, and the secret scanner that enforces it |

## The commands

| Document | Command |
| --- | --- |
| [agentq.md](agentq.md) | `agentq`, the GitHub backlog coordinator |
| [sandcastle.md](sandcastle.md) | `agentbox`, the unattended agent sandbox and its import boundary |
| [repo-labels.md](repo-labels.md) | `repo-labels`, the exact-sync GitHub label tool |
| [repo-meta.md](repo-meta.md) | `repo-meta`, the exact-sync GitHub About metadata and repository settings tool |
| [python-dev.md](python-dev.md) | The `python-dev` environment and its toolchain |

`devbox` has no separate reference yet. The router is described in
[architecture.md](architecture.md), and its environments in
[environments.md](environments.md).

## The `daniel` profile

These describe the complete personal workstation on Bazzite. Read them when you
converge that machine, or when you want the reasoning behind a default. A reader
who installs one component does not need them.

| Document | What it covers |
| --- | --- |
| [architecture.md](architecture.md) | The current machine: the host and container layers, the router, the agent configuration, and the trust boundary |
| [recovery.md](recovery.md) | The whole-machine path, from a fresh Bazzite installation to a verified workstation |
| [bootstrap.md](bootstrap.md) | The two whole-machine bootstrap scripts, and the libraries they share with the component installer |

## Release

| Document | What it covers |
| --- | --- |
| [public-release-audit.md](public-release-audit.md) | The public-readiness audit, its findings, the GO decision, and the `publication-gate` command that re-checks it |
| [naming.md](naming.md) | The repository-name evaluation, the decision, and what reopens it |
