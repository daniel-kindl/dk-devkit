# workstation

A version-controlled definition of a Bazzite KDE development workstation.

The goal is narrow and practical: a fresh Bazzite installation must be able to
use this repository to rebuild the development and agent environment, with as
little manual work as the tools allow.

This repository holds **configuration, manifests and installers**. It holds no
credentials, no session state and no toolchain payloads. See
[docs/secrets.md](docs/secrets.md).

## The shape of the machine

    Bazzite host                          isolated, purpose-specific containers
    ------------                          -------------------------------------
    Homebrew CLI tools                    web-dev      Node 22 + pnpm  (exists)
    Flatpak desktop apps                  dotnet-dev   planned
    Git + GitHub over SSH                 rust-dev     planned
    Orca (~/.local/bin/orca-ide)          android-dev  planned
    ~/projects  <- source checkouts
    ~/.local/bin/devbox  <- the router

The host keeps no language toolchain. Node, pnpm and the agent CLIs live inside
`web-dev`. The `devbox` router decides which container owns the current Git
repository, and runs the command there. The `claude` and `codex` commands on the
host are shims that go through the router, so Orca launches an agent on the host
and the agent runs in the correct container.

Unattended agents are the other half. `agentbox` runs an agent with no human
present, in a Podman container that is destroyed afterwards, against a
disposable clone of the repository. The real repository is never mounted, and
only validated commits are imported onto an `agent/` branch. It never pushes.
Read [docs/sandcastle.md](docs/sandcastle.md).

Read [docs/architecture.md](docs/architecture.md) for the full picture.

## Rebuild a machine

Full instructions, including every manual step, are in
[docs/recovery.md](docs/recovery.md). The short form:

```bash
# 1. On a fresh Bazzite install, get Git and Homebrew, then the SSH key.
ujust install-brew
ssh-add ~/.ssh/id_ed25519          # restore the key first; see docs/secrets.md

# 2. Clone this repository.
mkdir -p ~/projects
git clone git@github.com:daniel-kindl/workstation.git ~/projects/workstation

# 3. Build the host: packages, router, shims, and the web-dev container.
~/projects/workstation/bootstrap/host.sh

# 4. Build the container: toolchain, agent CLIs, shared configuration, skills.
~/.local/bin/devbox exec web-dev --cwd ~/projects/workstation -- ./bootstrap/web-dev.sh

# 5. Authenticate. This step is manual on purpose.
gh auth login --git-protocol ssh
~/.local/bin/devbox exec web-dev -- claude    # then /login
~/.local/bin/devbox exec web-dev -- codex login

# 6. Prepare unattended agent runs (optional).
claude setup-token                        # then edit ~/.config/agentbox/secrets.env
agentbox build

# 7. Check the result.
~/projects/workstation/verify.sh
```

Both bootstrap scripts are idempotent. Run them again at any time. They check
the current state first and change only what does not match. Anything they
replace is copied into `~/.agents/backups/<timestamp>/` first. Add `--dry-run`
to see what a run would change.

## Layout

| Path | What it holds |
| --- | --- |
| `bootstrap/` | The two installers: `host.sh` and `web-dev.sh` |
| `distrobox/` | `web-dev.ini`, a Distrobox Assemble manifest |
| `manifests/` | What to install: Homebrew, Flatpak, packages, toolchain versions, skills |
| `config/agents/` | The canonical shared agent policy and the status line |
| `config/devbox-router/` | The router configuration and inference rules |
| `config/claude/`, `config/codex/` | Non-secret client preferences |
| `config/web-dev/` | Files that belong to the container: shell fragment, Orca bridge |
| `bin/` | The router, `agentbox`, the verification suites and the other tools |
| `containers/` | The Containerfiles for the agent control plane and its sandboxes |
| `config/sandcastle/` | The orchestration programs that run inside the control plane |
| `verify/` | The verification modules that `./verify.sh` runs |
| `docs/` | Architecture, bootstrap, recovery, and the secret policy |
| `.devbox` | The router declaration: this repository is edited in `web-dev` |

## Verify

```bash
./verify.sh              # everything, with the fast devbox suite
./verify.sh --full       # also launch the real agent CLIs
./verify.sh --no-devbox  # skip the devbox routing suite
./verify.sh --only 3     # one module group
```

`verify.sh` runs from either side: on the host, or inside the `web-dev`
container. It changes nothing, except that module 9 runs the pre-existing
`devbox-verify` suite, which uses its own scratch directory and removes it
again.

## Writing policy

The prose in this repository follows ASD-STE100. `config/agents/AGENTS.md` holds
the policy, and it is the same file that Claude Code and Codex read as their
global instructions.
