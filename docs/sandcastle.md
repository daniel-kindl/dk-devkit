# Agent orchestration (Sandcastle)

## What this adds

The workstation already routes an **interactive** agent into the development
environment that owns a repository. `devbox` does that, and a human watches the
result.

This subsystem adds the other half: an **unattended** agent. It runs with no
human at the keyboard, in a container that is destroyed afterwards, against a
**disposable clone** of a repository. Only commits that pass validation on the
host reach the real repository, and only on an `agent/` branch. The tool is
`bin/agentbox`, and it drives
[Sandcastle](https://github.com/mattpocock/sandcastle) (`@ai-hero/sandcastle`).

    devbox     interactive agent   ->  a long-lived development environment
    agentbox   unattended agent    ->  a disposable clone, one branch, no push

## The boundary

This is the most important section. Everything else follows from it.

    real repository
      -> the host clones it into ~/.local/share/agentbox/runs/<run-id>/repo
      -> Sandcastle runs only against that disposable clone
      -> the agent commits inside the disposable clone
      -> the host validates the result
      -> validated commits are imported as one agent/<name> branch
      -> the clone, the sandbox and the run directory are removed

**The real repository is never bind-mounted into a sandbox.** Its path is not
in any `-v` argument, its `.git` is not reachable, and its working tree does
not exist inside the container. A sandbox therefore cannot:

| The sandbox cannot | Why not |
| --- | --- |
| read or write `<real-repo>/.git` | the path does not exist inside it |
| move any ref in the real repository | same |
| change the real repository's git config | same |
| install a hook in the real repository | same |
| change the checked-out working tree | same |
| escape by running `git update-ref`, writing `.git/config`, or writing `.git/hooks/*` | every one of those hits the disposable clone |

Every run proves the first five from inside the running sandbox: `agentbox`
passes the real repository path, `~/.agents` and the canonical skill store as
`forbiddenPaths`, and the orchestrator asserts that none of them exists there.
`agentbox selftest --adversarial` proves the sixth by carrying the attack out.

The clone is made with `git clone --no-hardlinks`. That flag is not a
preference. A local clone hardlinks its object files by default, so the clone
and the real repository would share inodes, and a write through the clone
would be a write to a real object. `--template=` points at an empty directory,
so the clone gets no sample hooks, and the `origin` remote is removed
immediately: nothing inside the disposable clone names the repository it came
from.

### What the sandbox still gets

The disposable clone's `.git` directory, read-write. That is unavoidable: a
git worktree carries no object store of its own.
`<clone>/.sandcastle/worktrees/<branch>/.git` is a **file** holding one line,
`gitdir: <clone>/.git/worktrees/<branch>`, and Sandcastle's
`resolveGitMounts()` follows that pointer and mounts both. The difference from
the old design is what that git directory belongs to: a clone this run made
and this run deletes, not the repository a human works in.

## Commit transfer

The transfer is the one place where anything from the sandbox enters the real
repository. It runs on the **host**, in `bin/agentbox`, after the sandbox is
destroyed.

### Nothing from the clone is executed

Everything a git repository can configure is a command git would otherwise
run: an alias, a pager, an fsmonitor, a clean or smudge filter, a credential
helper, an upload-pack hook, a hook script. The clone was writable by the
sandbox, so all of them are treated as hostile.

`sanitize_clone` removes `hooks/`, `worktrees/`, `modules/`,
`objects/info/alternates` and `config.worktree`, and restores `.git/config`
from the byte-for-byte copy the host took at clone time. It then **proves** the
restore: the config must compare equal to the pristine copy, the hook
directory must be empty, and the alternates file must be gone. A mismatch is a
refusal, not a repair.

Every host git command against the clone additionally runs with
`GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_SYSTEM=/dev/null`,
`GIT_ASKPASS=/bin/false`, `GIT_SSH_COMMAND=/bin/false`,
`GIT_ALLOW_PROTOCOL=file`, and a `core.hooksPath` pointing at an empty
directory the host created and no container ever saw.

### What is validated

Nothing is imported unless every one of these holds:

1. the agent branch exists in the clone and names a commit
2. that commit descends from the base commit the run started at
3. the range holds at least one commit and at most `--max-commits`
   (`AGENTBOX_MAX_COMMITS`, default 20)
4. the range holds no merge commit, unless `--allow-merges` was passed
5. the target branch is inside `agent/` and passes `git check-ref-format`
6. the real repository's refs, `HEAD`, config, hooks and working tree are
   byte-for-byte what they were when the run started
7. the target ref is still exactly what it was when the run started

The objects then move with one `git fetch` from the clone into a temporary
`refs/agentbox/import/<run-id>`, with `fetch.fsckObjects` and
`transfer.fsckObjects` on, so a malformed object graph is rejected before any
branch moves. The fetched commit is compared against the validated one.

The branch update is the compare-and-swap form:

    git update-ref refs/heads/<branch> <new> <old>

An empty `<old>` means the ref must not exist. This enforces invariant 7 a
second time, atomically, so a ref that moved between the check and the write
fails the write instead of being clobbered.

Afterwards the repository is compared against the baseline once more, and the
run fails if anything other than `refs/heads/<branch>` differs.

**If any invariant is uncertain, nothing is imported.** A run that fails, times
out, or cannot be validated leaves the real repository exactly as it was and
keeps the run directory for inspection.

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

## What the control plane gets

Narrow, and only from the run directory:

    <run-dir>/repo         the disposable clone, read-write
    <run-dir>/staging      the staged policy, skills, orchestrator and config, read-only
    <run-dir>/creds        the per-run credential file, read-only
    /run/user/1000/podman/podman.sock   the Podman API socket

It does **not** get `~/projects`, a sibling repository, this checkout, `~/.ssh`,
an ssh-agent socket, or a writable `~/.agents`. It is never told where the real
repository is, beyond the list of paths it proves are absent from the sandbox.

`verify.sh` module 8 reads every `-v` argument in `bin/agentbox` and fails if
one of them names anything but the socket, the clone, or the run directory.

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

### Host and container paths

`web-dev` mounts the host `~/projects` at `/workspace`. Both spellings reach the
same directory *from inside the container*, but only one of them exists for the
host Podman engine:

    podman run -v /home/dkindl/.local/share/agentbox/runs/x/repo:/mnt ...  works
    podman run -v /workspace/...:/mnt                                     statfs: no such file or directory

`agentbox` therefore tracks two spellings of every path: `*_HOST`, which Podman
is told, and `*_VIEW`, which this side opens with `cat`, `git` and `mkdir`.
Inside `web-dev` the view spelling goes through `/run/host`.

Because the real repository is no longer mounted, it no longer has to live
under `~/projects`, and it no longer has to ignore `.sandcastle/`: Sandcastle's
worktrees are created inside the disposable clone.

## The lifecycle

`agentbox pipeline` runs this, in order:

1. validate the branch name, resolve the base commit, and take the branch lock
2. record the real repository's refs, `HEAD`, config, hooks and working tree
3. clone the repository into the run directory with `--no-hardlinks`
4. stage the agent policy, the skills, the orchestrator and the configuration
5. write the per-run credential file, mode 600
6. start the control plane with a wall-clock limit
7. create the isolated branch, worktree and Podman sandbox inside the clone
8. prove no key material, no Podman socket and no real repository path reached
   the sandbox
9. run the implementer agent (Claude)
10. deterministic verification
11. optional independent reviewer (Codex)
12. deterministic verification
13. destroy the sandbox
14. compare the real repository against the baseline; it must be identical
15. sanitize the clone, validate the result, and import it as `agent/<name>`
16. compare again; exactly one ref may have moved
17. remove the credential file, the clone and the run directory

The branch strategy is always an explicit named branch. Sandcastle's `head` and
`merge-to-head` strategies are never selected, so nothing `agentbox` configures
merges into the checked-out branch.

## The run directory

    ~/.local/share/agentbox/runs/<run-id>/
        repo/       the disposable clone
        staging/    policy, skills, orchestrator and the run configuration
        creds/      the per-run credential file, mode 600
        meta/       the integrity snapshots and the pristine clone config

    ~/.local/share/agentbox/locks/<key>.lock

Nothing here is a canonical workstation path. That is the point: see SELinux,
below.

The credential file is removed as soon as the control plane exits, even when
the run directory is kept for inspection. A successful run removes the whole
directory; a failed one keeps it and says where it is. `agentbox clean` sweeps
run directories older than a day, and `agentbox clean --all` sweeps all of
them, along with every lock and every stray container.

## SELinux

Sandcastle's Podman provider takes a `selinuxLabel` option and defaults it to
`"z"`. `agentbox` passes `"z"` as well, because without it SELinux denies the
rootless container access to the bind mounts. `formatVolumeMount()` appends the
flag to **every** mount, so `podman` relabels each mount source on the host,
recursively and permanently.

That is why no canonical path is a mount source any more. Every sandbox mount
comes out of the run directory:

    <run-dir>/repo/.sandcastle/worktrees/<branch>   the worktree
    <run-dir>/repo/.git                             the disposable git directory
    <run-dir>/staging/policy                        a copy of config/agents
    <run-dir>/staging/skills                        a copy of the skill store
    <run-dir>/creds                                 the credential file

The canonical `config/agents`, the canonical `~/.agents/skills`, the real
repository and its `.git` are **copied from, never mounted**. After a run they
carry exactly the labels they carried before it, and the paths that were
relabelled no longer exist.

`agentbox selftest --adversarial` records the recursive contexts of the real
repository, of `config/agents` and of the skill store before the run, reads
them again afterwards, and fails on any difference.

The control plane keeps one deliberate relaxation: it runs with
`--security-opt label=disable`, because SELinux denies a confined container
process the `connect()` on the Podman socket, and the alternative is the
host-wide `container_connect_any` boolean. The **sandboxes keep their full
SELinux confinement**; Sandcastle never passes that flag, and `verify.sh`
module 8 fails if a second `label=disable` appears in `bin/agentbox`.

## Policy and skills in a sandbox

The sandbox agent obeys the same rules as an interactive one. Each run copies
the policy and the skills into its own staging directory and mounts the
**copies** read-only:

    config/agents/AGENTS.md  -> <run-dir>/staging/policy/  -> /opt/agents/policy  (ro)
    ~/.agents/skills         -> <run-dir>/staging/skills/  -> /opt/agents/skills  (ro)

The image links both into place:

    ~/.claude/CLAUDE.md  -> /opt/agents/policy/AGENTS.md
    ~/.codex/AGENTS.md   -> /opt/agents/policy/AGENTS.md
    ~/.claude/skills     -> /opt/agents/skills

An agent therefore cannot rewrite the policy that governs it, and cannot reach
the canonical store that every interactive agent on this machine reads.

## Credentials

Credentials live in `~/.config/agentbox/secrets.env`, mode 600, outside this
repository. `bootstrap/host.sh` creates the file as a commented template and
never writes a value.

| Agent | Variable | How to get it |
| --- | --- | --- |
| Claude | `CLAUDE_CODE_OAUTH_TOKEN` | `claude setup-token` on the host |
| Claude | `ANTHROPIC_API_KEY` | an API key, as an alternative |
| Codex | `OPENAI_API_KEY` | an API key |

That file is the **only** source. An interactive shell often exports
`ANTHROPIC_API_KEY` for its own use, and taking it silently would hand an
unattended sandbox a credential the user did not choose to delegate.
`--use-ambient-credentials` asks for that on purpose.

### No credential value is ever an argument

`agentbox` copies the values it needs into `<run-dir>/creds/agent.env`, mode
600, and mounts that file read-only into the sandbox at
`/opt/agents/credential/agent.env`. The sandbox image puts
`/opt/agents/bin/agent-cli-shim` in front of `claude` and `codex` on `PATH`.
The shim **reads** the file — it never sources it, because a sourced file is
code — parses `KEY=VALUE` lines, exports them, and execs the real CLI.

The value is therefore:

- never in a `podman` argument, on either hop
- never in the control plane's environment
- never in `/proc/<pid>/cmdline`

The orchestrator asserts this from inside the sandbox on every run: the
credential file must be present and `CLAUDE_CODE_OAUTH_TOKEN`,
`ANTHROPIC_API_KEY` and `OPENAI_API_KEY` must all be empty in the container
environment.

### Output redaction

Everything the control plane writes passes through a filter that replaces the
exact configured credential values with `[redacted credential]` before the
output reaches the terminal or a log. The values are exported into the filter,
not passed as arguments.

**This is defense in depth, and nothing more.** The sandbox has a network
connection and holds the credential, so an agent that wants to exfiltrate it
can. Redaction stops the accidental case, where a tool prints its own
environment into the run log. It does not stop a deliberate one.

### Sharing

The implementer and the reviewer share a container, so a configured
`OPENAI_API_KEY` is present for the whole run, not only during the review step.
That is the cost of keeping both agents on one branch in one sandbox.

When `OPENAI_API_KEY` is absent, the pipeline **skips** the review step and says
so. The implementation branch is still validated and imported. This is
deliberate: delegating the interactive ChatGPT sign-in to a disposable sandbox
is a larger exposure than an independent review is worth.

## Runtime controls

| Control | What it does |
| --- | --- |
| `--timeout SECONDS` | wall-clock limit for the whole run; `AGENTBOX_TIMEOUT_SECONDS` sets the default. `timeout --foreground --kill-after=30s` bounds the control plane, and the orchestrator aborts the agent a minute earlier so the sandbox can still be destroyed cleanly |
| branch lock | two runs cannot claim the same branch of the same repository. A lock whose run directory is gone, or which is older than the run could be, is broken once and reported |
| `--max-commits N` | the import bound |
| `--allow-merges` | accepts merge commits in the imported range |
| `--check CMD` | a deterministic check. A newline in the argument is refused, not split into two checks |
| `INT` and `TERM` | remove the control plane, remove this run's sandboxes, remove the credential file, release the lock |
| `agentbox clean` | sweeps stray containers, stale locks and stale run directories |

`--max-iterations` bounds the number of agent turns; `--timeout` bounds how
long they may take in total.

### The control plane does not read the terminal

`podman run` gets no `-i`, and its stdin is `/dev/null`. The orchestrator reads
nothing from stdin, and a podman client that reads the terminal from a
**background** process group takes `SIGTTIN`. Podman forwards that signal to the
container rather than stopping, which livelocks its attach loop: it stops
draining the container's stdout, and the orchestrator blocks on its next write.
The run then looks like a hang at teardown until the wall-clock limit kills it.

A background process group is the normal case here — `agentbox ... &` puts the
client in one, and so does `timeout`, which runs its child in its own group
unless `--foreground` says otherwise. `agentbox` passes `--foreground` as well,
so an interrupt still reaches the client.

## What never enters a sandbox

| Never | Why |
| --- | --- |
| the real repository, or its `.git` | the boundary this design exists for |
| the private SSH key | it stays on the host, as `docs/secrets.md` requires |
| the ssh-agent socket | an unattended agent must not be able to authenticate as the user |
| the Podman socket | a sandbox that can reach it can create any container |
| `~/.claude/.credentials.json` | the interactive session credential is not the unattended one |
| `~/.codex/auth.json` | a full ChatGPT sign-in is more than a sandbox needs |
| the canonical `~/.agents` or skill store | an agent must not rewrite the policy that governs it, and a mount would relabel it |
| a credential in an argument or an environment variable | it would appear in a process listing |

Because the sandbox holds no push credential, it **cannot** push to GitHub,
open a pull request, or merge there, even if a prompt told it to. The sandbox
does have a network, so "it cannot reach GitHub" is false; "it cannot
authenticate to GitHub" is what holds.

`agentbox selftest` proves each row from inside a running sandbox, and the same
probes run on every `run` and `pipeline`. Pass `--no-isolation-check` to skip
them.

## Honest limits

- **The sandbox has an unrestricted network.** The Podman provider passes no
  `--network`, so the sandbox reaches the internet, which is what the agent CLI
  needs. It cannot *authenticate* to GitHub, because it holds no key and no
  token; it can still reach any public host, and it can send the credential it
  holds anywhere. Output redaction does not change this.
- A process that can reach the Podman socket can create a privileged container.
  The control plane holds that authority by necessity, because Sandcastle has to
  create containers. Keeping it non-privileged limits what a bug in the runner
  reaches; it does not change what a deliberate misuse of the socket could do.
  Do not add anything else to the runner image that does not need to be there.
- The control plane can read the per-run credential file, because Sandcastle
  validates every sandbox mount source from inside the runner. It never places
  the value in an argument or in its own environment.
- A full clone per run costs disk and time proportional to the repository. The
  run directory is removed on success and kept on failure; `agentbox clean`
  sweeps what a killed process left.
- A run imports the committed state only. Uncommitted work in the real
  repository is not visible to the agent, because the clone starts from a
  commit.
- The images are built locally and are not signed. The base images are floating
  tags, not digests, and the sandbox image installs the Claude and Codex CLIs
  from an installer script fetched at build time.
- Parallel runs are possible: each takes its own branch, its own run directory
  and its own lock. Nothing schedules them.

## Commands

```bash
agentbox build                      # build the runner and sandbox images
agentbox doctor                     # what is ready, what is missing
agentbox selftest                   # prove the lifecycle on a throw-away repository
agentbox selftest --adversarial     # attack the git directory and prove it reached nothing
agentbox clean                      # remove stray containers, stale locks and run dirs
agentbox clean --all                # remove every run directory and lock as well

agentbox run \
  --repo ~/projects/example \
  --branch agent/example \
  --prompt-file ./prompt.md

agentbox pipeline \
  --repo ~/projects/example \
  --branch agent/example \
  --prompt-file ./prompt.md \
  --check 'npm test' \
  --check 'npm run typecheck' \
  --timeout 1800
```

`agentbox help` lists every option.

## Exit codes

| Code | Meaning |
| --- | --- |
| 2 | usage error |
| 3 | the repository argument is not a usable Git repository |
| 4 | a required image is missing |
| 5 | no usable Podman connection |
| 6 | a credential is missing or has the wrong permissions |
| 7 | refused: the branch is unsafe |
| 8 | the agent run itself failed; nothing was imported |
| 9 | the result was refused at import; the real repository did not change |
| 10 | the run passed its wall-clock limit; nothing was imported |
| 11 | another run holds the branch |
