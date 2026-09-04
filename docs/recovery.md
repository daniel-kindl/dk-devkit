# Recovery: from a fresh Bazzite installation to a working workstation

Follow the steps in order. Steps marked **MANUAL** cannot be automated, because
they need a human, a secret, or a browser.

## 0. What you need before you start

- A fresh Bazzite KDE installation, logged in as your own user.
- Your SSH private key, from your own backup. A password manager works well;
  this workstation installs Bitwarden as a Flatpak for exactly this.
- Your GitHub, Anthropic and OpenAI accounts.

## 1. MANUAL: install Homebrew

Bazzite ships a helper for this.

```bash
ujust install-brew
exec bash -l                       # pick up the Homebrew PATH
brew --version
```

`git` and `jq` already ship in the Bazzite image, so nothing else is needed to
clone the repository.

## 2. MANUAL: restore the SSH key

The key is the one thing this repository refuses to carry. See
[secrets.md](secrets.md).

```bash
install -m 700 -d ~/.ssh
install -m 600 /path/to/id_ed25519     ~/.ssh/id_ed25519
install -m 644 /path/to/id_ed25519.pub ~/.ssh/id_ed25519.pub
ssh-add ~/.ssh/id_ed25519
ssh -T git@github.com
```

The ssh-agent is a systemd user service. KDE Plasma sets `SSH_AUTH_SOCK` to
`$XDG_RUNTIME_DIR/ssh-agent.socket` and starts the agent on demand, so there is
nothing to configure. Distrobox mounts `/run/user/1000` into every container,
which is how `web-dev` reaches the same agent without a copy of the key.

## 3. Clone this repository

```bash
mkdir -p ~/projects
git clone git@github.com:daniel-kindl/workstation.git ~/projects/workstation
```

Clone it to exactly `~/projects/workstation`. The bootstrap links live
configuration into the checkout, so the path matters. See "The checkout is
load-bearing" in [architecture.md](architecture.md).

## 4. Bootstrap the host

```bash
~/projects/workstation/bootstrap/host.sh            # add --dry-run to preview
```

This step:

- creates `~/projects` and `~/.local/bin`
- installs the Homebrew taps, formulae and casks in `manifests/homebrew.txt`
- installs the Flatpak applications in `manifests/flatpaks.txt`
- links `devbox`, `devbox-verify`, `devbox-run` and `web-dev-run` into `~/.local/bin`
- generates the `claude` and `codex` shims with `devbox new-shim`
- links the router configuration into `~/.config/devbox-router`
- seeds an empty `repos.tsv`, and never overwrites an existing one
- creates the `web-dev` container from `distrobox/web-dev.ini`
- installs the shared policy file and the status line into the host Codex home

Log out and back in if `~/.local/bin` is not yet on your `PATH`.

## 5. Bootstrap the web-dev container

```bash
~/.local/bin/devbox exec web-dev --cwd ~/projects/workstation -- ./bootstrap/web-dev.sh
```

This step:

- installs `git`, `jq` and `gh` inside the container
- installs nvm, Node, Corepack and pnpm at the versions in `manifests/toolchain.env`
- installs the Claude Code and Codex native CLIs
- wires `~/.agents`, `~/.claude` and `~/.codex` to the shared policy and skills
- installs the Orca bridge wrappers and `sync-agent-skills`
- installs the 43 skills in `manifests/skills.tsv`, then runs `sync-agent-skills`
- applies the shared status line to both clients

## 6. MANUAL: authenticate GitHub

Once on the host, and once inside the container. They use separate homes.

```bash
gh auth login --git-protocol ssh
devbox exec web-dev -- gh auth login --git-protocol ssh
```

Set your Git identity if it is not restored from elsewhere:

```bash
git config --global user.name  "Your Name"
git config --global user.email "you@example.com"
devbox exec web-dev -- git config --global user.name  "Your Name"
devbox exec web-dev -- git config --global user.email "you@example.com"
```

## 7. MANUAL: authenticate the agent CLIs

```bash
devbox exec web-dev -- claude          # then run /login
devbox exec web-dev -- codex login
```

Both open a browser on the host.

## 8. MANUAL: install and register Orca

1. Download the Orca AppImage and put it in `~/AppImages/`.
2. Make it executable and start it once. Gear Lever, which
   `manifests/flatpaks.txt` installs, handles the desktop entry.
3. Let Orca register its CLI. On Linux it installs
   `~/.local/bin/orca-ide`, because the name `orca` belongs to the GNOME Orca
   screen reader.
4. Confirm it: `orca-ide --version`.

The container-side wrappers need no separate step. `bootstrap/web-dev.sh`
already links `orca` and `orca-ide` inside the box to the tracked bridge script.

## 9. Restore the repository assignment, if you want it

The router resolves `dkkb` from its `package.json` with no configuration. The
existing `devbox-verify` suite expects an explicit assignment, so add it if you
want that suite to report `source = global`:

```bash
git clone git@github.com:<owner>/dkkb.git ~/projects/dkkb
devbox assign web-dev ~/projects/dkkb
```

## 10. Verify

```bash
~/projects/workstation/verify.sh
```

Expect every module to pass. `--full` also launches the real agent CLIs through
the host shims, which is slower but proves the whole path end to end.

---

## Repairing an existing machine

Both bootstrap scripts are idempotent, so the repair for almost everything is to
run them again.

| Symptom | Fix |
| --- | --- |
| `claude` on the host does nothing useful | `bootstrap/host.sh` |
| A skill is missing or stale | `bin/install-skills` |
| Codex cannot see a skill | `sync-agent-skills` |
| A client rewrote its own status line | `~/.agents/statusline/install.sh` |
| Routing resolves the wrong environment | `devbox doctor` |
| The container is broken beyond repair | see below |

### Recreating the web-dev container

This destroys the isolated HOME, which holds the agent authentication. Only do
it deliberately.

```bash
devbox exec web-dev -- true                    # confirm it is really unusable
podman rm -f web-dev                           # the isolated HOME survives this
distrobox assemble create --file ~/projects/workstation/distrobox/web-dev.ini
devbox exec web-dev --cwd ~/projects/workstation -- ./bootstrap/web-dev.sh
```

`podman rm -f` removes the container, not `~/.local/share/distrobox-homes/web-dev`.
The HOME survives, so authentication survives with it. Remove that directory
only if you intend to re-authenticate everything.

Never use `distrobox assemble create --replace`: it removes the container and
can take the isolated HOME with it.
