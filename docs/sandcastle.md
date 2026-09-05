# Agent orchestration (Sandcastle)

## What this adds

The workstation already routes an **interactive** agent into the development
environment that owns a repository. `devbox` does that, and a human watches the
result.

This subsystem adds the other half: an **unattended** agent. It runs with no
human at the keyboard, in a container that is destroyed afterwards, on a branch
that no human is using. The tool is `bin/agentbox`, and it drives
[Sandcastle](https://github.com/mattpocock/sandcastle) (`@ai-hero/sandcastle`).

    devbox     interactive agent   ->  a long-lived development environment
    agentbox   unattended agent    ->  a disposable sandbox, one branch, no push

## The four layers

| Layer | What it is | What owns it |
| --- | --- | --- |
| Orca | the interactive agent and worktree UI | the host |
| devbox + purpose-specific Distroboxes | the interactive development runtime | this repository |
| Sandcastle behind `agentbox` | unattended and parallel agent orchestration | this repository |
| Podman | the local sandbox provider | the host |
| GitHub | durable issue, pull request and CI state | remote |

`agentbox` stops at the branch. It never pushes, so GitHub only ever sees what a
human decides to send.

## Why the control plane is not a Distrobox

The obvious design is a fourth Distrobox called `agent-runner`. The evidence
rules it out.

`distrobox-create` 1.8.2.5 builds every container with a fixed argument list:

    --privileged
    --security-opt label=disable
    --security-opt apparmor=unconfined
    --user root:root

Those flags are unconditional. The `--unshare-*` options change the ipc, net,
pid and device namespaces; none of them removes the privilege. A Distrobox is
therefore always a privileged, label-disabled, root container. That is the right
trade for an interactive environment that has to integrate with the host. It is
the wrong trade for a process that runs unattended model output.

So the control plane is a plain OCI image instead:
`containers/agent-runner/Containerfile`. It is not privileged, it runs as
uid 1000, and `podman run --rm` destroys it when the run ends.

The other reason is path arithmetic, below.

## Podman connection design

Sandcastle's Podman provider calls the `podman` binary on `PATH` and passes
bind mounts as `-v <hostPath>:<sandboxPath>`. The **host** Podman resolves
`hostPath` in its own mount namespace.

The control plane runs inside a container, so it needs a client that reaches the
host engine. It uses `podman-remote` against the rootless host API socket:

    /run/user/1000/podman/podman.sock

Every container Sandcastle creates is therefore a **sibling** on the host, not a
nested child. Nothing needs nesting privilege.

    host Podman (rootless)
      |
      +-- agent-runner        the control plane, not privileged, --rm
      |
      +-- sandcastle-<uuid>   the sandbox, not privileged, destroyed on close

The runner image installs the same `podman-remote` version that the host runs,
so the client and the API server agree.

### Host and container repository paths

This is the part that a remapped mount breaks.

`web-dev` mounts the host `~/projects` at `/workspace`. Both spellings reach the
same directory *from inside the container*, but only one of them exists for the
host Podman engine:

    podman run -v /home/dkindl/projects/workstation:/mnt ...   works
    podman run -v /workspace/workstation:/mnt ...              statfs: no such file or directory

The control plane therefore mounts `~/projects` at the **identical host path**,
not at `/workspace`. There is exactly one spelling of every repository path, and
it is the one the host engine understands. `agentbox` also translates a
`/workspace/...` argument back to its host spelling before it uses it, so the
command works from either side.

Sandcastle puts each worktree under the repository it came from:

    <repo>/.sandcastle/worktrees/<branch>

That path is inside `~/projects`, so the host engine can mount it. Every
repository that `agentbox` drives must ignore `.sandcastle/`.

## The lifecycle

`agentbox pipeline` runs this, in order:

1. validate the repository, and refuse when the requested branch is the one that
   is checked out
2. create the isolated branch and worktree
3. create the Podman sandbox
4. run the implementer agent (Claude)
5. deterministic verification
6. optional independent reviewer (Codex)
7. deterministic verification
8. leave the branch for human review
9. destroy the sandbox
10. compare the repository against the baseline taken at step 1, and fail the
    run when anything outside the agent branch moved

The branch strategy is always an explicit named branch. Sandcastle's `head` and
`merge-to-head` strategies are never selected, so nothing `agentbox` configures
merges into the checked-out branch.

`agentbox` refuses any branch that does not start with `agent/`, and refuses any
name `git check-ref-format` rejects. That prefix is in
`manifests/sandcastle.env`.

Read the next section before you rely on that prefix.

## The branch prefix is a policy, not a boundary

This is the most important limit in the design, and the one that is easiest to
read past.

A git worktree does not carry its own object store. `<repo>/.sandcastle/worktrees/<branch>/.git`
is a **file** holding one line:

    gitdir: <repo>/.git/worktrees/<branch>

Sandcastle's bind-mount provider follows that pointer. `resolveGitMounts()`
reads the file, resolves the parent, and mounts **both**:

    <worktree>/.git   ->  the same path in the sandbox
    <repo>/.git       ->  the same path in the sandbox

Neither mount is read-only. So a process inside the sandbox holds the
repository's shared ref database and object store, read-write, and can:

- write any ref, including `refs/heads/main`, with `git update-ref`
- rewrite `.git/config`, where an `alias`, `core.pager` or `core.fsmonitor`
  value is a command that git later runs **on the host**
- install a `.git/hooks/` script that the next human `git commit` runs on the
  host

`agentbox` cannot remove those mounts without leaving Sandcastle's worktree
model, so it does the next best thing: it **detects** the abuse and fails.
Before the sandbox exists, `orchestrate.mjs` records every ref and its object,
the branch `HEAD` points at, the local `git config`, and an inventory of
`.git/hooks`. After the sandbox is destroyed it takes the same record and
compares. Anything that moved outside the agent branch is printed as a
violation and the run exits non-zero.

That converts a silent compromise into a loud one. It does not prevent it.

**Point `agentbox` at a repository you are willing to have an unattended agent
touch.** A clone you can throw away is the safe choice; the repository you are
working in is not.

## What never enters a sandbox

| Never | Why |
| --- | --- |
| the private SSH key | it stays on the host, as `docs/secrets.md` requires |
| the ssh-agent socket | an unattended agent must not be able to authenticate as the user |
| the Podman socket | a sandbox that can reach it can create any container |
| `~/.claude/.credentials.json` | the interactive session credential is not the unattended one |
| `~/.codex/auth.json` | a full ChatGPT sign-in is more than a sandbox needs |
| a writable `~/.agents` | an agent must not rewrite the policy that governs it |

Because the sandbox holds no push credential, it **cannot** push to GitHub,
open a pull request, or merge there, even if a prompt told it to.

What it does receive, and what the table above does not cover, is the
repository's own `.git` directory, read-write. See "The branch prefix is a
policy, not a boundary". The sandbox has a network, so "it cannot reach GitHub"
is false; "it cannot authenticate to GitHub" is what holds.

`agentbox selftest` proves each row of the table from inside a running sandbox,
and the isolation probes run on every `run` and `pipeline` as well. Pass
`--no-isolation-check` to skip them.

## Policy and skills in a sandbox

The sandbox agent obeys the same rules as an interactive one. Two read-only
mounts do that:

    config/agents            -> /opt/agents/policy   (from this checkout)
    ~/.agents/skills         -> /opt/agents/skills   (the shared skill store)

The image links both into place:

    ~/.claude/CLAUDE.md  -> /opt/agents/policy/AGENTS.md
    ~/.codex/AGENTS.md   -> /opt/agents/policy/AGENTS.md
    ~/.claude/skills     -> /opt/agents/skills

Both mounts are read-only on both hops: into the runner, and from the runner
into the sandbox.

## Credentials

Credentials live in `~/.config/agentbox/secrets.env`, mode 600, outside this
repository. `bootstrap/host.sh` creates the file as a commented template and
never writes a value.

| Agent | Variable | How to get it |
| --- | --- | --- |
| Claude | `CLAUDE_CODE_OAUTH_TOKEN` | `claude setup-token` on the host |
| Claude | `ANTHROPIC_API_KEY` | an API key, as an alternative |
| Codex | `OPENAI_API_KEY` | an API key |

`agentbox` passes only the variables an agent needs, as environment variables on
the container. Nothing is written to disk in the repository or in a worktree.

They reach the sandbox through the **sandbox** provider, not the agent provider.
Sandcastle builds the container with `podman run -e ...` and drives it afterwards
with `podman exec`, which passes no environment of its own, so the container
environment is fixed at creation time. `createSandbox()` does not know the agent
yet at that moment, so an agent provider's `env` arrives too late and the CLI
reports `Not logged in`. Sandcastle also throws when the two `env` maps share a
key, so the credentials live in exactly one of them.

One consequence: the implementer and the reviewer share a container, so a
configured `OPENAI_API_KEY` is present for the whole run, not only during the
review step. That is the cost of keeping both agents on one branch in one
sandbox.

When `OPENAI_API_KEY` is absent, the pipeline **skips** the review step and says
so. The implementation branch is still left for a human. This is deliberate:
delegating the interactive ChatGPT sign-in to a disposable sandbox is a larger
exposure than an independent review is worth.

## What a run changes on the host

Two host-side effects outlive a run. Neither is a bug in `agentbox`, and both
are easy to be surprised by.

### Every bind mount is relabelled

Sandcastle's Podman provider takes a `selinuxLabel` option and defaults it to
`"z"`. `agentbox` passes `"z"` as well, because without it SELinux denies the
rootless container access to the bind mounts. `formatVolumeMount()` appends the
flag to **every** mount, so `podman` relabels each mount source on the host,
recursively:

    <repo>/.sandcastle/worktrees/<branch>    the worktree
    <repo>/.git                              the shared git directory
    <this checkout>/config/agents            the shared policy
    ~/.agents/skills                         the shared skill store

Those paths change from `user_home_t` to `container_file_t` and **stay**
changed after the run. The lower-case `z` is the *shared* label, so every other
container on the machine can then read them; `:ro` makes the mount read-only
inside this container, it does not make the host label read-only.

Check what a run relabelled:

```bash
ls -dZ ~/.agents/skills ~/projects/<repo>/.git
```

Restore a path when you want the original type back:

```bash
restorecon -R -v ~/.agents/skills
```

`restorecon` is a no-op for anything under `/run/user/<uid>/`: the shipped
`file_contexts` maps `/run/user/[^/]+/.+` to `<<none>>`, so there is no
default context to restore. Recreate the file instead — for the Podman API
socket, `systemctl --user restart podman.socket`.

### The control plane's one deliberate relaxation

The control plane runs with `--security-opt label=disable`.

SELinux denies a confined container process the `connect()` on the Podman
socket, and the alternative is the host-wide `container_connect_any` boolean,
which would apply to every container on the machine. The narrower change is the
one flag, on the one container that already holds container-creation authority.

The **sandboxes keep their full SELinux confinement**. Sandcastle never passes
that flag, and `verify.sh` module 8 fails if a second `label=disable` ever
appears in `bin/agentbox`.

## Honest limits

- **The sandbox holds `<repo>/.git` read-write.** The `agent/` prefix is a
  policy the orchestrator checks afterwards, not a boundary the sandbox is held
  inside. A `.git/config` or `.git/hooks` write is host-side code execution the
  next time a human runs git in that repository. See "The branch prefix is a
  policy, not a boundary". Use a disposable clone.
- A process that can reach the Podman socket can create a privileged container.
  The control plane holds that authority by necessity, because Sandcastle has to
  create containers. Keeping it non-privileged limits what a bug in the runner
  reaches; it does not change what a deliberate misuse of the socket could do.
  Do not add anything else to the runner image that does not need to be there.
- A run relabels its bind mount sources on the host and does not put them back.
  See "What a run changes on the host".
- **The sandbox has an unrestricted network.** The Podman provider passes no
  `--network`, so the sandbox reaches the internet, which is what the agent CLI
  needs. It cannot *authenticate* to GitHub, because it holds no key and no
  token; it can still reach any public host.
- **The credential is visible in a process listing.** `agentbox` passes the
  token as `-e NAME=VALUE`, so it appears in the `podman` client's `argv` and in
  `/proc/<pid>/cmdline`, readable by the same user and by root. Sandcastle
  passes the sandbox environment the same way inside the runner.
- **Agent output is not redacted.** The runner streams the agent's stdout
  straight through. An agent that prints its own environment prints the token
  with it, into your terminal and into anything capturing that output.
- **There is no wall-clock timeout.** `--max-iterations` bounds the number of
  agent turns, not how long one takes.
- The images are built locally and are not signed. The base images are floating
  tags, not digests, and the sandbox image installs the Claude and Codex CLIs
  from an installer script fetched at build time.
- `agentbox` runs one sandbox per invocation. Parallel runs are possible because
  each takes its own branch, but nothing schedules them yet, and nothing locks a
  branch against a second run using the same name.

## Commands

```bash
agentbox build                    # build the runner and sandbox images
agentbox doctor                   # what is ready, what is missing
agentbox selftest --repo PATH     # prove the sandbox lifecycle, no credential
agentbox clean                    # remove stray sandbox and control-plane containers

agentbox run \
  --repo ~/projects/example \
  --branch agent/example \
  --prompt-file ./prompt.md

agentbox pipeline \
  --repo ~/projects/example \
  --branch agent/example \
  --prompt-file ./prompt.md \
  --check 'npm test' \
  --check 'npm run typecheck'
```

`agentbox help` lists every option.
