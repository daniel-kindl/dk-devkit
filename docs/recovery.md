# Recovery: from a fresh Bazzite installation to a working workstation

Follow the steps in order. Steps marked **MANUAL** cannot be automated, because
they need a human, a secret, or a browser.

This is the whole-machine path for the `daniel` profile on Bazzite. To install
one part of the toolkit instead, read [components.md](components.md) and run
`./install.sh --components <ids>`.

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
- generates the `agentq` shim, pinned to the environment that the internal
  `manifests/agentqueue.env` manifest names
- removes the obsolete installed `agentqueue` entry point
- links the router configuration into `~/.config/devbox-router`
- seeds an empty `repos.tsv`, and never overwrites an existing one
- creates the container of every supported environment module, such as
  `web-dev` from `distrobox/web-dev.ini`
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
- installs the real `agentq` coordinator runtime
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

## 8. MANUAL: prepare unattended agent runs

`bootstrap/host.sh` already installed `agentbox` and created
`~/.config/agentbox/secrets.env` as an empty, commented template. Two steps
remain, and both are yours.

Mint a **dedicated** token for unattended use, and put it in that file:

```bash
claude setup-token                      # on the host; opens a browser
$EDITOR ~/.config/agentbox/secrets.env  # set CLAUDE_CODE_OAUTH_TOKEN
```

Do not copy the token out of an interactive session. A dedicated token can be
revoked on its own. `OPENAI_API_KEY` in the same file is optional; without it,
the pipeline skips the independent review step and says so.

Then build the images and check the result:

```bash
agentbox build      # a few minutes; it pulls two base images
agentbox doctor     # expect: ready
```

`agentbox selftest` proves the whole sandbox lifecycle on a throw-away
repository it creates itself, without spending a token.
`agentbox selftest --adversarial` goes further: the sandbox attacks its own git
directory on purpose, and the run proves that the real repository, its config,
its hooks and its SELinux labels are all unchanged. Run both after a rebuild.
See `docs/sandcastle.md`.

## 8b. Prepare the backlog coordinator, if you want an unattended run

`bootstrap/web-dev.sh` installs the coordinator inside the container, and
`bootstrap/host.sh` installs the `agentq` command on the host. The coordinator
lives in the container because it needs `gh` and the forwarded ssh-agent; the
host command is a router shim that delegates to it.

It needs no credential of its own. It uses the `gh` sign-in from step 6 and the
SSH key from step 2, and it never writes either to disk.

```bash
cd ~/projects/dkkb
agentq doctor
agentq plan
```

The explicit form still works, and it is the one to reach for when the shim
itself is what you doubt:

```bash
devbox exec web-dev --cwd ~/projects/dkkb -- agentq doctor
```

`plan` reads GitHub and changes nothing. It prints which issues are runnable
and which are blocked, and it ends with the count of attempted mutations, which
must be zero.

A repository opts in to an automatic merge in its existing tracked
`.agentqueue.json` policy. `agentq init` writes a starting point into the
repository you stand in. The policy filename is retained as a durable format
identifier; the supported command is `agentq`.
Read `docs/agentq.md` before turning `autoMerge` on.

## 9. MANUAL: install and register Orca

1. Download the Orca AppImage and put it in `~/AppImages/`.
2. Make it executable and start it once. Gear Lever, which
   `manifests/flatpaks.txt` installs, handles the desktop entry.
3. Let Orca register its CLI. On Linux it installs
   `~/.local/bin/orca-ide`, because the name `orca` belongs to the GNOME Orca
   screen reader.
4. Confirm it: `orca-ide --version`.

The container-side wrappers need no separate step. `bootstrap/web-dev.sh`
already links `orca` and `orca-ide` inside the box to the tracked bridge script.

## 10. Restore the repository assignment, if you want it

The router resolves `dkkb` from its `package.json` with no configuration. The
existing `devbox-verify` suite expects an explicit assignment, so add it if you
want that suite to report `source = global`:

```bash
git clone git@github.com:<owner>/dkkb.git ~/projects/dkkb
devbox assign web-dev ~/projects/dkkb
```

## 11. Verify

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
| An unattended agent run fails to start | `agentbox doctor` |
| `agentq: command not found` on the host | run `bootstrap/host.sh`; the shim lives in `~/.local/bin` |
| `agentq` exits 127 | the runtime is missing in the container; run `bootstrap/web-dev.sh` |
| A backlog run will not start | `agentq doctor` |
| The queue merged nothing, and every issue looks blocked | `agentq plan` |
| An issue is stuck with `agent-in-progress` | the claim goes stale on its own; `agentq plan` reports it |
| A sandbox container, lock or run directory was left behind | `agentbox clean`, or `agentbox clean --all` |
| The agent images are stale | `agentbox build --force` |
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
