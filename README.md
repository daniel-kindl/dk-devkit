# dk-devkit

Reusable development tools, agent workflows, environment definitions, and automation that power Daniel's software-development setup.

This repository is evolving from a Bazzite workstation definition into a **portable personal development toolkit**. Reusable commands and workflows are the product; Daniel's complete workstation becomes one opinionated composition of those pieces. Bazzite/Fedora remains the primary verified platform today.

> The toolkit architecture is in place: modular component installation, interactive selection, named profiles, and the platform capability layer all exist as `./install.sh`. Bazzite is the only platform with verification evidence; the other adapters carry the support tier the evidence allows, and this README does not present them as verified. `dotnet-dev` and `android-dev` are declared modules without an installation. Remaining work is tracked in #52 and #53.

## Current tools

### `install.sh`

Installs reusable components. It resolves the dependency and capability closure of what you name, shows the plan, converges in deterministic order, and verifies only what it selected.

```bash
./install.sh                      # pick the components on a terminal
./install.sh --list
./install.sh --doctor             # what this machine is, and what it can install
./install.sh --state              # public configuration versus machine-local state
./install.sh --dry-run --components web-dev
./install.sh --components agentbox
./install.sh --profile developer
```

A component declares its dependencies, the platform capabilities its installation needs, and where its public configuration ends and machine-local state begins. `--state` reports that boundary and changes nothing. Public configuration is tracked here; machine-local state, credentials and private machine identity stay outside Git. Read [docs/components.md](docs/components.md) and [docs/not-tracked.md](docs/not-tracked.md).

With no selection, and only on a terminal, it opens a component picker. `--profile` selects a tracked component set: `minimal`, `developer`, `agent-dev` or `daniel`. An automated run that names nothing gets a usage error instead of a prompt.

A component asks for capabilities, never for a distribution. A platform adapter says how this machine supplies a capability, and what a human runs to obtain a missing one. `./install.sh --doctor` reports all of it and changes nothing. Read [docs/platforms.md](docs/platforms.md).

### `devbox`

Routes interactive commands into the development environment that owns a repository. The current primary environment is `web-dev`, a Fedora Distrobox with an isolated home and the web/Node agent toolchain.

```bash
devbox doctor
devbox exec web-dev --cwd ~/projects/example -- pnpm check
```

Host `claude` and `codex` shims use the same router so interactive agents execute in the repository's development environment.

Each environment is an independent module: `web-dev`, `python-dev` and `rust-dev` are installable today, and `dotnet-dev` and `android-dev` are declared but not implemented. Read [docs/environments.md](docs/environments.md).

### `agentbox`

Runs an unattended coding agent against a **disposable clone** in an isolated Podman sandbox. The real repository is not mounted into the model sandbox. `agentbox` validates the result before importing accepted commits onto an `agent/*` branch and never receives GitHub push or merge authority.

```bash
agentbox doctor
agentbox build
agentbox selftest
agentbox selftest --adversarial
```

Read [docs/sandcastle.md](docs/sandcastle.md) for the security and runtime architecture.

### `agentq`

Coordinates a GitHub issue backlog in the trusted layer. It selects runnable issues, drives `agentbox`, scans validated diffs, pushes branches, opens pull requests, waits for configured checks/review gates, and merges only when repository policy permits.

```bash
cd ~/projects/dkkb
agentq setup
agentq doctor
agentq plan
agentq run
```

Installing the coordinator and preparing a repository are separate operations. `./install.sh --components agentq` installs the command once per machine. `agentq setup` inspects one repository and reports what is still missing: the policy file, the base branch, the local checks, the workflow labels, and the authentication this side holds. It starts no backlog work, and it never rewrites repository labels. Label drift is reported with the [`repo-labels`](docs/repo-labels.md) command that repairs it.

The host command is a router shim; the real coordinator currently runs inside `web-dev`, where `gh` and the forwarded SSH agent are available. Read [docs/agentq.md](docs/agentq.md).

The coordinator's public name is `agentq`. Some durable internal identifiers intentionally keep the older `agentqueue` name, including `.agentqueue.json`, existing run-state paths, internal configuration variables, and historical claim markers.

### `repo-labels` and `repo-meta`

Two GitHub repository settings are tracked here rather than typed into a web form, so that each one is reviewable in a pull request and checkable afterwards.

```bash
repo-labels check                 # label drift against manifests/github-labels.json
repo-meta check                   # About metadata and repository settings drift
repo-meta sync --dry-run          # the exact plan, without changing anything
```

`repo-meta` holds the description, the homepage and the topics a reader sees, and the settings that decide which surfaces exist and how a branch is merged: the default branch, issues, wiki, projects, discussions, the three merge methods, and the deletion of a merged head branch. A setting the manifest does not name stays unmanaged.

Both read the existing `gh` login and hold no credential of their own. Both refuse a destructive sync without confirmation, because deleting a label removes it from issues and pull requests, removing a topic removes the repository from that topic search, turning a surface off hides the content in it, and retargeting the default branch moves where every new clone lands. Read [docs/repo-labels.md](docs/repo-labels.md) and [docs/repo-meta.md](docs/repo-meta.md).

## Current architecture

```text
Bazzite/Fedora host
|
+-- devbox --+-------------------> web-dev Distrobox
|            |                     +-- Node / pnpm
|            |                     +-- Claude Code
|            |                     +-- Codex
|            |                     `-- agentq runtime
|            |
|            +-------------------> python-dev Distrobox
|            |                     +-- Python / uv
|            |                     `-- Claude Code, Codex
|            |
|            `-------------------> rust-dev Distrobox
|                                  +-- Rust / cargo, through rustup
|                                  `-- Claude Code, Codex
|
+-- agentbox
|    +-- disposable clone
|    +-- agent-runner control plane
|    `-- disposable model sandbox
|
`-- agentq host shim
     `-- trusted GitHub coordinator in web-dev
```

Each environment has its own isolated home, and the router picks the one that
owns a repository. `dotnet-dev` and `android-dev` are declared modules with no
installation yet.

The trust boundary is deliberate:

- `agentq` is trusted and can use GitHub/SSH authority.
- `agentbox` is the trusted driver around disposable execution and import validation.
- model output runs in a disposable sandbox without GitHub or SSH authority.
- the development Distrobox is a convenience/development environment, **not** a hostile-code security boundary.

See [docs/architecture.md](docs/architecture.md) for the full current workstation architecture.

## Toolkit direction

The target shape is independently reusable components that declare capabilities and dependencies instead of assuming one Bazzite machine:

```text
personal development toolkit
|
+-- commands
|   +-- devbox
|   +-- agentbox
|   +-- agentq
|   `-- repository tools
|
+-- agent workflows / policies / skills
+-- development environments
+-- platform capability adapters
`-- profiles
    +-- minimal
    +-- developer
    +-- agent-dev
    `-- daniel
```

Each profile contains the smaller one. The `daniel` profile composes the complete personal workstation. No profile is a dependency of a reusable tool, and `./install.sh --dry-run --profile daniel` shows what it resolves to.

Current roadmap priorities are tracked in [#52](https://github.com/daniel-kindl/dk-devkit/issues/52) and [#53](https://github.com/daniel-kindl/dk-devkit/issues/53). The architectural epics [#8](https://github.com/daniel-kindl/dk-devkit/issues/8) and [#24](https://github.com/daniel-kindl/dk-devkit/issues/24) are complete.

The repository was renamed from `workstation` to `dk-devkit` to name the product rather than one machine. [docs/naming.md](docs/naming.md) records that evaluation. GitHub redirects the old URL. A checkout made before the rename keeps working after `git remote set-url origin`, and the checkout directory is `~/projects/dk-devkit`.

## Platform support

Every platform below has an adapter in `manifests/platforms.json`. The tier states the verification evidence, not the intent.

| Platform | Tier | Status |
| --- | --- | --- |
| Bazzite | `verified` | Primary implementation and verification target |
| Fedora | `supported` | Same family, not verified on this machine |
| Debian/Ubuntu | `experimental` | Adapter exists; the next family that must prove the abstraction |
| Arch Linux | `experimental` | Adapter exists; follows Debian |
| macOS | `unsupported` | Adapter exists; no component is verified there |
| Windows | none | WSL2 preferred before native support; the report says when it runs under WSL |

An adapter does not imply that every component works everywhere. `./install.sh --doctor` reports which components this machine can install, and a component the machine cannot supply is blocked before anything is installed. In particular, `agentbox` requires security/runtime properties that a platform must prove before it can be considered supported.

## Current setup

Two entry points converge the same state. `./install.sh` installs a selected part; the bootstrap scripts install the whole machine. Both call the same library functions.

On Bazzite/Fedora:

```bash
# Clone the repository.
mkdir -p ~/projects
git clone git@github.com:daniel-kindl/dk-devkit.git ~/projects/dk-devkit

# Configure the host and create web-dev when absent.
~/projects/dk-devkit/bootstrap/host.sh

# Configure the web-dev environment.
~/.local/bin/devbox exec web-dev --cwd ~/projects/dk-devkit -- ./bootstrap/web-dev.sh

# Verify the current installation.
~/projects/dk-devkit/verify.sh
```

To install one part instead of the whole machine:

```bash
~/projects/dk-devkit/install.sh --dry-run --components agentbox
~/projects/dk-devkit/install.sh --components agentbox
```

Every installer converges existing state rather than blindly replacing it. Use `--dry-run` to preview changes.

Full recovery instructions are in [docs/recovery.md](docs/recovery.md).

## Authentication and private state

Credentials and authentication state are not repository configuration.

The repository does not intentionally track:

- SSH private keys;
- GitHub tokens;
- Claude or Codex credentials/session state;
- machine-local secrets;
- generated run logs;
- private overrides.

See [docs/secrets.md](docs/secrets.md) for the policy, and `./install.sh --state` for the public and local boundary of each component.

[docs/public-release-audit.md](docs/public-release-audit.md) is the public-readiness audit: what a reader of the public repository learns, what was classified as intentionally public, and the steps publication still owes. `bin/publication-gate` runs the mechanical gates of that audit against the exact commit and prints one verdict.

## Repository layout

| Path | Purpose |
| --- | --- |
| `install.sh` | Component installer entry point |
| `components/` | Component contracts and their install, doctor, and verify operations |
| `bin/` | Reusable commands and utilities |
| `lib/agentqueue/` | Internal Python implementation behind the public `agentq` command |
| `bootstrap/` | Convergence libraries, and the whole-machine host and environment scripts |
| `distrobox/` | Current development-environment definitions |
| `containers/` | Agent control-plane and sandbox images |
| `config/` | Public non-secret configuration and agent/runtime policy |
| `manifests/` | Package, toolchain, skill, capability, platform, and runtime version declarations |
| `verify/` | Deterministic verification modules and probes |
| `docs/` | Toolkit, command, and workstation documentation; [docs/README.md](docs/README.md) is the index |

Component operations live with their component. Existing files move only when the component contract makes the new boundary useful.

## Verification

```bash
./verify.sh              # normal verification
./verify.sh --full       # includes slower real-agent routing checks
./verify.sh --no-devbox  # skip the devbox routing suite
./verify.sh --list       # list verification modules
```

Some verification is deliberately machine-specific because this repository is also the source of truth for Daniel's real setup. Portable component verification will be separated as the toolkit architecture matures.

## Project policies

- Technical prose follows the repository's ASD-STE100 policy in `config/agents/AGENTS.md`.
- Security-sensitive changes must preserve the `agentbox` sandbox/import boundary and `agentq` authority boundary.
- Platform support claims require verification evidence.
- Credentials and private machine state stay outside Git.

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and the documentation index in [docs/README.md](docs/README.md).

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
