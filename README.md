# workstation

Reusable development tools, agent workflows, environment definitions, and automation that power Daniel's software-development setup.

This repository is evolving from a Bazzite workstation definition into a **portable personal development toolkit**. Reusable commands and workflows are the product; Daniel's complete workstation becomes one opinionated composition of those pieces. Bazzite/Fedora remains the primary verified platform today.

> The toolkit architecture is in transition. Current commands below exist now. Modular component installation, profiles, and broader platform adapters are roadmap work tracked in #8 and #24; this README does not present them as already implemented.

## Current tools

### `devbox`

Routes interactive commands into the development environment that owns a repository. The current primary environment is `web-dev`, a Fedora Distrobox with an isolated home and the web/Node agent toolchain.

```bash
devbox doctor
devbox exec web-dev --cwd ~/projects/example -- pnpm check
```

Host `claude` and `codex` shims use the same router so interactive agents execute in the repository's development environment.

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
agentq doctor
agentq plan
agentq run
```

The host command is a router shim; the real coordinator currently runs inside `web-dev`, where `gh` and the forwarded SSH agent are available. Read [docs/agentq.md](docs/agentq.md).

The coordinator's public name is `agentq`. Some durable internal identifiers intentionally keep the older `agentqueue` name, including `.agentqueue.json`, existing run-state paths, internal configuration variables, and historical claim markers.

## Current architecture

```text
Bazzite/Fedora host
|
+-- devbox ----------------------> web-dev Distrobox
|                                  +-- Node / pnpm
|                                  +-- Claude Code
|                                  +-- Codex
|                                  `-- agentq runtime
|
+-- agentbox
|    +-- disposable clone
|    +-- agent-runner control plane
|    `-- disposable model sandbox
|
`-- agentq host shim
     `-- trusted GitHub coordinator in web-dev
```

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

The planned `daniel` profile will compose the complete personal workstation. It will not be a hidden dependency of reusable tools.

Current roadmap priorities are tracked in [#8](https://github.com/daniel-kindl/workstation/issues/8) and [#24](https://github.com/daniel-kindl/workstation/issues/24).

## Platform support

| Platform | Status |
| --- | --- |
| Bazzite/Fedora | Primary current implementation and verification target |
| Debian/Ubuntu | Planned capability adapter |
| Arch Linux | Planned after the capability abstraction is proven |
| macOS | Future, component by component where requirements can be met |
| Windows | WSL2 preferred before native support |

A future adapter does not imply that every component will work everywhere. In particular, `agentbox` requires security/runtime properties that a platform must prove before it can be considered supported.

## Current setup

The repository still has a machine-oriented bootstrap while the component installer is being designed.

On Bazzite/Fedora:

```bash
# Clone the repository.
mkdir -p ~/projects
git clone git@github.com:daniel-kindl/workstation.git ~/projects/workstation

# Configure the host and create web-dev when absent.
~/projects/workstation/bootstrap/host.sh

# Configure the web-dev environment.
~/.local/bin/devbox exec web-dev --cwd ~/projects/workstation -- ./bootstrap/web-dev.sh

# Verify the current installation.
~/projects/workstation/verify.sh
```

Both bootstrap scripts are intended to converge existing state rather than blindly replace it. Use `--dry-run` where supported to preview changes.

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

See [docs/secrets.md](docs/secrets.md). Public defaults and local/private state are being formalized further under #14.

## Repository layout

| Path | Purpose |
| --- | --- |
| `bin/` | Reusable commands and utilities |
| `lib/agentqueue/` | Internal Python implementation behind the public `agentq` command |
| `bootstrap/` | Current host and `web-dev` convergence scripts |
| `distrobox/` | Current development-environment definitions |
| `containers/` | Agent control-plane and sandbox images |
| `config/` | Public non-secret configuration and agent/runtime policy |
| `manifests/` | Package, toolchain, skill, and runtime version declarations |
| `verify/` | Deterministic verification modules and probes |
| `docs/` | Architecture, recovery, security, and tool documentation |

The planned component/profile layout is a roadmap direction. Existing files will move only when the component contract makes the new boundary useful.

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

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
