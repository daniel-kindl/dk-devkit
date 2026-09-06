# Architecture

## Two layers, one boundary

The workstation has two layers. The boundary between them is deliberate, and
every design decision in this repository follows from it.

**The Bazzite host** is an image-based, immutable system. Bazzite owns the base
system, so this repository adds as little to it as possible:

- Homebrew, for a small set of host CLI tools
- Flatpak, for desktop applications
- Git, and GitHub authentication over SSH
- Orca, the agent IDE, installed as an AppImage
- `~/projects`, the one root for source checkouts
- `~/.local/bin/devbox`, the environment router
- `~/.local/bin/claude` and `~/.local/bin/codex`, shims that call the router

The host holds **no language toolchain**. There is no Node and no npm on the
host. `verify.sh` checks this, and reports a failure if one appears.

**A Distrobox container** holds one purpose-specific development environment.
`web-dev` and `python-dev` exist today. `dotnet-dev`, `rust-dev` and
`android-dev` are planned modules: each declares its container name and the
router markers it owns, and nothing else yet. `docs/environments.md` describes
the module.

Each container has its own isolated HOME, so its dotfiles never reach the host
home:

    ~/.local/share/distrobox-homes/web-dev

The host `~/projects` is mounted into the container at `/workspace`. Everything
outside that mount is still reachable at `/run/host/<path>`, because Distrobox
mounts the host root there.

## The devbox router

`bin/devbox` runs on the host. It answers one question: *which development
environment owns this Git repository?* It then translates the working directory
into the container and executes the command there.

Resolution order, first match wins:

1. `$DEVBOX_ENV` — an explicit override
2. `<repo>/.devbox` — a committed, repository-local declaration
3. `<git-common-dir>/devbox-env` — a per-clone, uncommitted declaration
4. `repos.tsv` — a global assignment
5. `inference.tsv` — automatic, and only when the match is unambiguous
   (assembled from `components/*/inference.tsv`)
6. otherwise it fails, and prints what to do next

A repository is identified by
`git rev-parse --path-format=absolute --git-common-dir`. Every Git worktree
therefore inherits its primary checkout. The worktrees that Orca creates under
`~/projects/.worktrees` need no configuration of their own.

If the markers of a repository point at more than one environment, the router
fails with exit code 7. It does not guess.

`config/devbox-router/README.md` holds the full reference, including the exit
codes and the environment file keys.

This repository uses rule 2 on itself. It holds no language-toolchain marker,
so `inference.tsv` cannot resolve it, and a `repos.tsv` entry would be machine
state. The tracked `.devbox` file at the repository root declares `web-dev`, so
every clone routes the same way.

### Why the agent shims exist

Orca launches a bare `claude` or `codex` from the host. Both names resolve to a
shim in `~/.local/bin`. The shim calls `devbox agent <tool>`, which resolves the
environment from the worktree and runs the real binary inside the container. The
agent, and everything the agent spawns, stays in that environment.

The shims refuse to run inside a container. That recursion guard is why an agent
inside `web-dev` reaches the real `claude` binary and not the shim. The router
also strips the host `~/.local/bin` from the container `PATH` for the same
reason, because Distrobox forwards the host `PATH` verbatim.

## Shared agent configuration

`~/.agents` is the canonical cross-agent configuration area. It lives inside the
`web-dev` HOME, because that is where the agent CLIs run.

    ~/.agents/AGENTS.md      -> config/agents/AGENTS.md   (this repository)
    ~/.agents/statusline     -> config/agents/statusline  (this repository)
    ~/.agents/skills/        the canonical third-party skill store
    ~/.claude/CLAUDE.md      -> ~/.agents/AGENTS.md
    ~/.codex/AGENTS.md       -> ~/.agents/AGENTS.md
    ~/.claude/skills         -> ~/.agents/skills
    ~/.codex/skills/<name>   -> ~/.agents/skills/<name>   (one link per skill)
    ~/.codex/skills/.system  Codex native skills, never touched

Claude Code accepts one directory symlink for the whole skill store. Codex needs
one symlink per skill, because `~/.codex/skills/.system` holds the Codex native
skills and must survive. `bin/sync-agent-skills` maintains those links, and it
never deletes a real directory.

The link targets use the host spelling of the checkout
(`~/projects/workstation/...`), not `/workspace/...`. Both spellings reach the
same files from inside the container, but only the host spelling also resolves
from the host. That is what lets `verify.sh` run from either side.

### The checkout is load-bearing

The wiring above uses symlinks, not copies. A `git pull` therefore updates the
live configuration, and an edit to the live configuration is an edit to the
repository. The cost is that `~/projects/workstation` must stay in place. Delete
it and the shared policy, the status line and the router all break. `verify.sh`
reports a dangling link as a failure.

## Status line

`config/agents/statusline/spec.json` is the canonical specification. Both
clients render the same fields in the same order:

    <model + effort> | <project> | <branch> | PR #<n>
      | ctx <n>% left (<tokens> used) | 5h <n>% left | week <n>% left

Claude Code runs an arbitrary command, so `claude-render.sh` does the render. It
takes every value from the JSON payload on stdin, except the Git branch, which
comes from a local `git` call. It makes no network call.

The renderer also forwards the payload to `~/.orca/agent-hooks/claude-statusline.sh`
when that hook exists. The forward runs in the background, so it cannot delay
the render. That is how the Orca status integration keeps working.

Codex does not run a script. It renders a fixed item list, set under `[tui]` in
`config.toml`. `install.sh` writes both, and it is idempotent.

### Two Codex homes

Codex has a home inside the container, and Orca points `CODEX_HOME` at a host
path that is already mounted into the container. Both homes are therefore real.
`bootstrap/host.sh` and `bootstrap/web-dev.sh` install the shared policy file and
the status line item list into both, so the result is the same whichever home is
active.

## Orca

Orca runs on the host. On Linux the executable is `~/.local/bin/orca-ide`,
because the name `orca` already belongs to the GNOME Orca screen reader. Inside
`web-dev`, both `orca` and `orca-ide` are wrappers that call
`distrobox-host-exec` and hand the call back to the host.

Orca writes its Claude Code hooks and its status line into the **host**
`~/.claude/settings.json`. Claude runs with the container HOME, so those hooks
would be inert. When `orca_integration = 1` and the Orca environment variables
are present, the router mirrors only the `hooks` and `statusLine` keys into the
container settings, and links the container `~/.orca` to the host copy. It
records what it wrote in `.devbox-orca-managed.json`, and it never overwrites a
value that was changed by hand.

Orca worktrees live under `~/projects/.worktrees`. They resolve through the
git-common-dir rule, so they need no entry in `repos.tsv`.

## Unattended agents

`devbox` routes an **interactive** agent into the environment that owns a
repository. `bin/agentbox` is the unattended counterpart: it runs an agent with
no human present, in a Podman container that is destroyed afterwards, on a
branch that no human is using.

The control plane is deliberately **not** a Distrobox. `distrobox-create` adds
`--privileged`, `--security-opt label=disable` and `--user root:root` to every
container it makes, and none of the `--unshare-*` options removes that. Those
are the right defaults for an interactive environment and the wrong ones for
unattended model output, so the control plane is a plain non-privileged OCI
image instead.

It reaches the host Podman through the rootless API socket, so each sandbox is
a sibling container on the host rather than a nested one. Every path it is
given is spelled the way the **host** spells it, because the host engine
resolves a bind mount in its own namespace, where `/workspace` does not exist.

The boundary is a **disposable clone**. Each run clones the target repository
into `~/.local/share/agentbox/runs/<run-id>/repo`, and the sandbox works only
there. The real repository is never bind-mounted, so a sandbox cannot read or
write its `.git`, move a ref, change its config, install a hook, or touch its
working tree: none of those paths exists inside the container. Every run proves
that from inside the running sandbox.

Afterwards the host validates the result — it must descend from the base
commit, stay under the commit bound, carry no unexpected merge, and target an
`agent/` branch that has not moved — and imports it with a compare-and-swap ref
update. Nothing from the clone is executed on the host: its config is restored
from the copy taken at clone time and its hooks are removed first. If any
invariant is uncertain, nothing is imported.

An unattended agent never receives the SSH key, the ssh-agent socket, the
Podman socket, the canonical `~/.agents`, or the canonical skill store. It
cannot push, open a pull request, or merge on GitHub, because it holds no
credential that would let it. The credential it does hold arrives as a
read-only file, never as an argument.

`docs/sandcastle.md` holds the full design and the limits.

## The GitHub backlog coordinator

`agentbox` stops at a validated `agent/*` branch. `bin/agentq` is the half
that carries the result the rest of the way:

    cd ~/projects/dkkb
    agentq run

It selects a runnable issue, drives `agentbox`, pushes the validated branch,
opens the pull request, waits for the GitHub checks, merges when every gate
passes, and scans the backlog again, because a merge can unblock the next
issue.

The split is the point. **`agentq` is trusted and `agentbox` is not.**

| Component | Holds |
| --- | --- |
| `agentq` | the `gh` sign-in, the host ssh-agent, the right to push, open a pull request and merge |
| `agentbox` | the disposable clone and the import validation. No GitHub credential |
| the sandbox | a model credential, a network. Nothing that authenticates to GitHub |

`agentq` hands `agentbox` a repository path, a branch name, a prompt file
and a set of limits. It hands a sandbox nothing at all. `verify.sh` module 8b
fails if the coordinator ever names a GitHub token, reads the agentbox
credential file, or passes an environment to the agentbox process.

It runs inside `web-dev`, because that is where `gh` is installed and where the
host ssh-agent socket is reachable. It is written in Python with the standard
library only, so the host rule against a Node toolchain is unaffected.

The command is still typed on the host, because that is where a person sits.
`~/.local/bin/agentq` is a devbox router shim, generated by
`devbox new-shim agentq --env web-dev` and pinned to the environment that
`manifests/agentqueue.env` names. It holds no runtime and no credential: it
translates the working directory and delegates.

    host terminal                     web-dev container
    cd ~/projects/dkkb
    agentq run             ---->  cd /workspace/dkkb
                                      agentq run

The shim resolves no repository. It carries the working directory across the
boundary, and the coordinator resolves the repository on the far side, from the
directory the router already translated. A shim that resolved it first would
hand over a host path that does not exist inside the container.

An explicit `--repo` is the same problem in the other direction: there the user
types a host path and the coordinator reads it inside. The router translates
that value too, because the shim names the option with `--map-path` and the
router owns the mapping. Git discovery still happens only in the coordinator.

A pinned shim differs from the `claude` and `codex` shims in one way. Those ask
the repository which environment owns it, because a repository decides where
its own toolchain lives. `agentq` is installed in one environment only, so
the working directory decides the repository and never the destination.

`docs/agentq.md` holds the dependency model, the claim model, the merge
gates and the failure taxonomy.

## Secrets

The private SSH key stays on the host, and only on the host. The host ssh-agent
socket is at `$XDG_RUNTIME_DIR/ssh-agent.socket`, and Distrobox mounts
`/run/user/1000` into the container, so the agent is available inside `web-dev`
with no extra configuration and no copied key.

`docs/secrets.md` states the full policy.
