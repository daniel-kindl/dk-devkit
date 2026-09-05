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

The branch strategy is always an explicit named branch. Sandcastle's `head` and
`merge-to-head` strategies are never selected, so the agent's commits cannot
reach the checked-out branch.

`agentbox` refuses any branch that does not start with `agent/`. That prefix is
in `manifests/sandcastle.env`.

## What never enters a sandbox

| Never | Why |
| --- | --- |
| the private SSH key | it stays on the host, as `docs/secrets.md` requires |
| the ssh-agent socket | an unattended agent must not be able to authenticate as the user |
| the Podman socket | a sandbox that can reach it can create any container |
| `~/.claude/.credentials.json` | the interactive session credential is not the unattended one |
| `~/.codex/auth.json` | a full ChatGPT sign-in is more than a sandbox needs |
| a writable `~/.agents` | an agent must not rewrite the policy that governs it |

Because the sandbox holds no push credential, it **cannot** push, open a pull
request, or merge, even if a prompt told it to.

`agentbox selftest` proves each of these from inside a running sandbox.

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

When `OPENAI_API_KEY` is absent, the pipeline **skips** the review step and says
so. The implementation branch is still left for a human. This is deliberate:
delegating the interactive ChatGPT sign-in to a disposable sandbox is a larger
exposure than an independent review is worth.

## The one deliberate relaxation

The control plane runs with `--security-opt label=disable`.

SELinux denies a confined container process the `connect()` on the Podman
socket, and the alternative is the host-wide `container_connect_any` boolean,
which would apply to every container on the machine. The narrower change is the
one flag, on the one container that already holds container-creation authority.

The **sandboxes keep their full SELinux confinement**. Sandcastle never passes
that flag, and `verify.sh` module 8 fails if a second `label=disable` ever
appears in `bin/agentbox`.

## Honest limits

- A process that can reach the Podman socket can create a privileged container.
  The control plane holds that authority by necessity, because Sandcastle has to
  create containers. Keeping it non-privileged limits what a bug in the runner
  reaches; it does not change what a deliberate misuse of the socket could do.
  Do not add anything else to the runner image that does not need to be there.
- The images are built locally and are not signed.
- `agentbox` runs one sandbox per invocation. Parallel runs are possible because
  each takes its own branch, but nothing schedules them yet.

## Commands

```bash
agentbox build                    # build the runner and sandbox images
agentbox doctor                   # what is ready, what is missing
agentbox selftest --repo PATH     # prove the sandbox lifecycle, no credential
agentbox clean                    # remove stray sandbox containers

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
