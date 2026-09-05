# The GitHub backlog coordinator (agentqueue)

## What this adds

`agentbox` runs one unattended agent against one repository and stops at a
validated `agent/*` branch. Everything after that was manual: write a prompt
file, start a run, push the branch, open a pull request, wait for the checks,
merge, then choose the next issue.

`agentqueue` is that missing half. One command drains a backlog:

```bash
cd ~/projects/dkkb
agentqueue drain --repo .
```

The command runs on the host. The coordinator runs inside `web-dev`. See
[Where it runs, and where you type it](#where-it-runs-and-where-you-type-it).

    agentbox     one issue,  no GitHub authority,  stops at a local branch
    agentqueue   the queue,  all GitHub authority, pushes, merges, rescans

## The boundary, again

This is the section that decides every other design choice. The workstation
already keeps unattended model output away from anything that authenticates.
`agentqueue` adds GitHub authority to the picture, so the boundary has to be
stated once more, with the new part in it.

| Component | Trust | Holds |
| --- | --- | --- |
| `agentqueue` | trusted, runs on this side | `gh` authentication, the host ssh-agent, the right to push, open a pull request and merge |
| `agentbox` | trusted host-side driver | the disposable clone, the import validation, no GitHub credential |
| the Sandcastle sandbox | **untrusted** | a model credential, a disposable clone, a network. Nothing else |

A sandbox receives no GitHub token, no SSH key, no ssh-agent socket and no
Podman socket. It cannot push, cannot open a pull request and cannot merge,
because it holds nothing that authenticates to GitHub. `agentqueue` adds
nothing to a sandbox: it hands `agentbox` a repository path, a branch name, a
prompt **file** and a set of limits, and `agentbox` decides what reaches the
container.

`verify.sh` module 8b proves the separation statically. It fails if
`agentqueue` ever names `GH_TOKEN`, `GITHUB_TOKEN`, `gh auth token`, the
agentbox credential file, or an environment for the agentbox process. It also
fails if the prompt builder ever names a model credential.

## The lifecycle

```
GitHub issue carries ready-for-agent
  -> the scheduler proves it is runnable
  -> the coordinator claims it, with a label and a machine-readable comment
  -> it builds the prompt from the issue, its comments and its referenced issues
  -> agentbox implements it in a disposable clone
       implement -> run the checks -> feed a failure back to the same agent
       -> repeat, up to maxFixRounds, inside the same sandbox
  -> agentbox imports a validated agent/* branch
  -> the coordinator scans the branch diff for a credential
  -> the coordinator pushes the branch
  -> it opens, or adopts, the pull request
  -> it waits for the GitHub checks
  -> a failure gets a bounded repair, as an agentbox continuation run
  -> every merge gate is re-read
  -> merge
  -> rescan, because a merge can unblock the next issue
```

The rescan is not an optimisation. Three issues where two wait for the first
need three scans, and a queue that scanned once would stop with work left.

## Two feedback loops

A single-shot agent that is graded afterwards wastes a whole run on a typo.
There are therefore two loops, and they cost very different amounts.

**The cheap loop lives inside the sandbox.** Sandcastle keeps one sandbox
across several `run()` calls, and commits accumulate on one branch. After the
implementer stops, the orchestrator runs the configured checks, and a failure
goes straight back to the **same agent**, in the **same sandbox**, with the
failing command and the tail of its output as the whole evidence. Nothing is
cloned again and no container is created again. `--max-fix-rounds` bounds it,
default 2.

**The expensive loop lives in the coordinator.** A GitHub check can only fail
after the sandbox is gone, so a repair there is a new clone, a new sandbox and
a new agent session. `maxRetries` bounds it, default 2. The budget is shared
with the local-check loop, so one issue can never spend more than the sum.

The prompt tells the implementer about the first loop in as many words: run the
checks yourself, repair what fails, and repeat.

## Continuation mode

A repair has to reach a branch that `agentbox` already imported.
`agentbox pipeline --continue` does that, and it preserves every import
invariant instead of working around one:

- the branch becomes its own base, so the clone starts at the current tip
- the result must still descend from that base
- the range is still bounded by `--max-commits`
- the ref update is still a compare and swap against the tip the run started
  from

The alternative, editing an imported branch on the host with an untrusted
agent, would put model output outside the sandbox. It is not available.

## The dependency model

`ready-for-agent` means **specified well enough for an implementation agent**.
It does not mean the work can start. An issue is runnable only when all of this
holds:

    the issue is open
    AND it carries the ready label
    AND no live claim holds it
    AND it carries neither the human label nor the failed label
    AND every blocker is satisfied

A blocker is satisfied when the blocking issue is closed.

Two sources, in this order:

1. **GitHub-native issue dependencies.** `GET
   /repos/{owner}/{repo}/issues/{n}/dependencies/blocked_by`. This is
   authoritative when the API answers.
2. **The repository prose convention.** A line such as `Blocked by ... #85` in
   the issue body. It is the documented fallback, and it is also read when the
   native source answered: anything it names is added to the blocker set, which
   can only make the answer more conservative.

**Fail closed.** Each of these refuses to start an issue:

| Situation | Answer |
| --- | --- |
| the dependency API errors | AMBIGUOUS |
| a blocker statement names no issue, and nothing else named one | AMBIGUOUS |
| a blocker lives in another repository | AMBIGUOUS |
| a blocker cannot be read | AMBIGUOUS |
| the issue sits on a dependency cycle | CYCLE, reported, never runnable |

The dkkb bodies name their blocker by title rather than by number, for example
`Blocked by "Implement homepage-eligibility module"`. On its own that is
ambiguous. GitHub's native graph records the same dependency as `#85`, so the
native answer settles it and the prose adds nothing. Turn the native source off
and the same issue becomes AMBIGUOUS rather than silently runnable.

A code fence is not a dependency statement. Fenced blocks and inline code are
removed before the body is read.

## Claiming

Two coordinators must not implement one issue twice. The claim is durable
GitHub state, because a coordinator can be killed and another can start on
another machine.

- **a label**, `agent-in-progress`, which a human sees in the issue list
- **a comment**, which carries the run id, the branch, the base commit and the
  start time, as prose and as one JSON block

GitHub offers no compare-and-swap on a label, so the claim is best effort and
this document says so. The race is narrowed like this:

1. add the label
2. post the claim comment
3. read every comment back
4. the **oldest live claim wins**

A coordinator that finds an older live claim deletes its own comment and leaves
the issue alone. A local lock directory holds the same claim on this machine,
so two runs from one terminal stop with no GitHub call at all. `agentbox` keeps
its own branch lock underneath both.

A claim with no release comment goes stale after `staleClaimSeconds`, or after
twice the limit its own run recorded, whichever is shorter. A stale claim is
taken over, and the takeover is reported in the summary rather than being
silent.

## Adopting existing work

A matching branch name proves nothing. Before an existing `agent/*` branch is
adopted, all of this must hold:

1. the issue is still open and still eligible
2. exactly one branch matches `agent/issue-<n>` or `agent/issue-<n>-*`
3. the branch names a commit
4. it shares history with the base, and it forked from the base branch
5. it adds between one and `maxCommits` commits
6. it carries no merge commit
7. **every commit is authored and committed by the agentbox identity**,
   `Agent <agent@local>`, read from `manifests/sandcastle.env`
8. it is not the branch this working tree has checked out
9. the repository is not in the middle of a merge, a rebase or a bisect

Rule 7 is the strong one. It is what separates work that `agentbox` produced
from a branch a human, or anything else, put in the same namespace. Turn it off
with `requireAgentAuthoredCommits: false` if a repository needs that, and know
what the option costs.

An **open** pull request whose head is the branch is adopted rather than
duplicated: its body is refreshed and the run continues from the checks. A
**merged or closed** pull request for the branch, with the issue still open, is
a contradiction, so the queue asks for a human instead of guessing.

## Nothing is published before the diff is read

A push is publication. A credential that reaches GitHub cannot be recalled by
deleting the branch afterwards. The whole diff of `base...branch` therefore
goes through `bin/scan-secrets --stdin` before every push, including the push
after a repair. A finding is a **queue-global** failure: nothing is pushed, and
the drain stops.

## The merge gates

An automatic merge happens only when every one of these passes, all of them
re-read at merge time:

- the issue is still open and still carries the ready label
- the dependencies are still satisfied
- `agentbox` imported a validated branch, or a valid branch was adopted
- the deterministic checks pass
- the pull request is open, and its head is exactly the verified commit
- the pull request targets the configured base branch
- GitHub says the pull request merges cleanly, and does not say "unknown"
- the required GitHub checks passed
- the review policy is satisfied
- the branch diff carries no credential

The merge call itself sends the expected head SHA, so GitHub refuses the merge
if the head moved between the last gate and the call. Afterwards the coordinator
reads the pull request again, and a merge it cannot confirm is a failure.

**The queue never merges on uncertainty.** A gate that cannot be answered is a
gate that failed.

## The review policy

`agentbox` runs an independent reviewer only when a reviewer credential is
configured. `OPENAI_API_KEY` is optional and stays optional. What a missing
review means is a policy choice, and it is written down rather than inferred:

| `reviewPolicy` | `mergeWithoutReview` | Result |
| --- | --- | --- |
| `required` | must be `false` | no review, no merge |
| `optional` | `false` (default) | the review runs when it can. A skipped review stops the merge |
| `optional` | `true` | the review runs when it can. A skipped review does not stop the merge |
| `none` | ignored | no review is attempted, and a merge needs no review |

The pull request body states which of these happened. It never claims a check
or a review that did not run.

An unattended backlog drain needs `optional` plus `mergeWithoutReview: true`,
and that combination is an explicit two-key decision on purpose.

## The failure taxonomy

| Outcome | What the queue does |
| --- | --- |
| `SUCCESS` | merge if the policy allows, then rescan |
| `BLOCKED` | leave the issue alone, evaluate another |
| `NEEDS_HUMAN` | add the human label, comment, continue with another issue |
| `FAILED_TRANSIENT` | retry inside the budget |
| `FAILED_FINAL` | add the failed label, comment, continue |
| `SECURITY_OR_INTEGRITY_FAILURE` | **stop the whole queue at once** |

A product failure belongs to one issue. A security failure belongs to the
machine.

These stop the queue:

- an agentbox isolation probe failed
- the disposable clone integrity comparison failed, or could not run
- the real repository moved during a run
- an import moved more than the agent branch
- the fetched commit is not the validated one
- the clone configuration could not be restored
- a branch diff matches a credential pattern
- **an agentbox import refusal that this code does not recognise**

The last row is the fail-closed rule. "The import was unsafe" and "the import
could not be shown to be safe" get the same answer.

## Configuration

Policy is declarative, and it is resolved from files. No repository is named in
any code path.

| Order | File | What it is for |
| --- | --- | --- |
| 1 | `config/agentqueue/policy.default.json` | the built-in policy, tracked here |
| 2 | `<repo>/.agentqueue.json` | **the right place.** Tracked with the repository it governs |
| 3 | `~/.config/agentqueue/repos/<owner>--<name>.json` | machine state, for a repository that cannot carry the file yet |
| 4 | `--config PATH` | an explicit override |

Later files overlay earlier ones key by key. An unknown key is a refusal, not a
warning: a mistyped key that a policy file silently ignored is how an operator
ends up believing a gate is on when it is off.

`.agentqueue.json` does not collide with `.devbox`. `.devbox` tells the router
which container owns the repository. `.agentqueue.json` tells the coordinator
what it may do with the backlog. Neither reads the other.

### The keys

| Key | Default | Meaning |
| --- | --- | --- |
| `baseBranch` | `main` | what a pull request targets |
| `branchPrefix` | `agent/` | the only namespace the coordinator may write |
| `issueLabel` | `ready-for-agent` | the backlog |
| `inProgressLabel` | `agent-in-progress` | the claim |
| `humanLabel` | `ready-for-human` | the queue gave up and said why |
| `failedLabel` | `agent-failed` | the implementation run failed |
| `dependencySources` | `["github","prose"]` | where blockers come from |
| `checks` | `[]` | deterministic checks, run inside the sandbox |
| `requiredChecks` | `[]` | GitHub check names that must pass. Empty means every check that reported |
| `requireCiChecks` | `true` | a commit with no check at all is not a pass |
| `ciTimeoutSeconds` | `1800` | how long to wait for the checks |
| `ciGraceSeconds` | `180` | how long a workflow has to appear |
| `reviewPolicy` | `optional` | see the review table |
| `mergeWithoutReview` | `false` | see the review table |
| `autoMerge` | `false` | merge when every gate passes |
| `mergeMethod` | `squash` | squash, merge or rebase |
| `maxParallel` | `1` | issues at a time |
| `maxRetries` | `2` | repair attempts per issue, shared across both loops |
| `maxFixRounds` | `2` | repair rounds inside one sandbox |
| `maxIterations` | `4` | agent turns per run |
| `maxCommits` | `20` | the import bound |
| `agentTimeoutSeconds` | `3600` | the wall-clock limit of one run |
| `staleClaimSeconds` | `7200` | when a claim with no release is stale |
| `adoptExistingBranch` | `true` | continue from validated work |
| `adoptExistingPullRequest` | `true` | do not open a second pull request |
| `requireAgentAuthoredCommits` | `true` | adoption rule 7 |
| `scanDiffForSecrets` | `true` | read the diff before publishing it |
| `referencedIssueDepth` | `1` | quote the issues an issue points at |
| `maxPromptBytes` | `60000` | the prompt size bound |

The shipped defaults refuse an automatic merge. A repository turns it on
deliberately.

### A policy for an autonomous drain

`agentqueue init --repo <path>` writes a starting point. A repository that
should drain without waiting for a human review needs this:

```json
{
  "version": 1,
  "baseBranch": "main",
  "issueLabel": "ready-for-agent",
  "checks": ["pnpm install --frozen-lockfile", "pnpm check"],
  "requiredChecks": ["Quality"],
  "reviewPolicy": "optional",
  "mergeWithoutReview": true,
  "autoMerge": true,
  "mergeMethod": "squash",
  "maxParallel": 1,
  "maxRetries": 2
}
```

`mergeWithoutReview: true` is the line that says "the deterministic checks and
the GitHub checks are enough for this repository". It is a choice, and it
belongs in a tracked file where a human can see it.

## Prompt construction

Nobody writes a prompt file. The coordinator is the trusted half, so it may
read GitHub, and it builds the prompt from:

- the issue number, title and full body
- the issue comments, minus the queue's own claim and release comments
- the acceptance criteria, taken from the `## Acceptance` checklist
- the specification and decision issues the body points at, quoted as context
- the base commit
- the configured checks, and the instruction to run them and repair what fails

The prompt tells the implementer to read the repository `AGENTS.md` and obey it.
It does not copy that file: the disposable clone already carries it, and a copy
would go stale.

It also states the limits in the register an unattended agent needs: implement
this issue only, add nothing the issue does not state, change no unrelated file,
weaken no test, ask no question.

The prompt names no credential and no credential path. A unit test asserts that.

## The commands

Run them from a host terminal. `PATH` may be relative, and `.` is the usual
choice, because the working directory travels with the command.

```bash
agentqueue drain  --repo PATH [options]   drain the backlog
agentqueue plan   --repo PATH             the plan, an alias of drain --dry-run
agentqueue doctor --repo PATH             what is ready, what is missing
agentqueue policy --repo PATH [--json]    the resolved policy and its sources
agentqueue init   --repo PATH [--local]   write a policy file to start from
```

Options for `drain`:

```
--label NAME          override the ready label
--base NAME           override the base branch
--config PATH         an explicit policy file
--max-parallel N      issues at a time
--max-retries N       repair attempts per issue
--merge-method M      squash, merge or rebase
--auto-merge          merge when every gate passes
--no-auto-merge       stop at a green pull request
--once                process one wave, then stop
--dry-run             print the plan and change nothing
```

### The dry run

`agentqueue plan` reads GitHub and changes nothing. It prints one line per
issue and the order the scheduler would use:

```
  #85 RUNNABLE
  #86 BLOCKED by #85
  #87 BLOCKED by #85

  order: #85
```

Every write method of the GitHub client and of the git wrapper passes through
one guard, and in dry-run mode that guard raises. A dry run that tried to
change durable state therefore fails loudly instead of changing it. The plan
ends with the count of attempted mutations, and a count above zero is a
coordinator defect. `verify.sh` module 8b proves statically that no write
method skipped the guard.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | the queue drained, or it is empty, or what is left is legitimately blocked |
| 1 | a coordinator defect |
| 2 | a usage error |
| 3 | the policy is unusable |
| 4 | a security or integrity failure stopped the queue |
| 5 | the machine is not ready |

## Where it runs, and where you type it

The coordinator runs **inside the `web-dev` container**. That is where `gh` is
installed, where the host ssh-agent socket is reachable, and where
`podman-remote` reaches the host engine. The host has no `gh` and, by rule, no
Node toolchain.

You type the command **on the host**, in a normal terminal:

```bash
cd ~/projects/dkkb
agentqueue plan  --repo .
agentqueue drain --repo .
```

`~/.local/bin/agentqueue` on the host is a devbox router shim, the same kind of
file as the `claude` and `codex` shims. It holds no runtime, no state and no
credential. `bootstrap/host.sh` generates it with

    devbox new-shim agentqueue --env web-dev --print

and the environment name comes from `AGENTQUEUE_ENVIRONMENT` in
`manifests/agentqueue.env`. The whole shim is one line of routing:

    exec "$router" exec web-dev --cwd "$PWD" -- agentqueue "$@"

### What the delegation preserves

| Property | How |
| --- | --- |
| the working directory | `--cwd "$PWD"`. The router maps the host path to the container path, so `~/projects/dkkb` becomes `/workspace/dkkb` |
| `--repo .` | the coordinator resolves `.` against the **translated** directory, so it means the same repository |
| the arguments | `"$@"` to the router, positional arguments to the container, `exec "$@"` inside it. Spaces, quotes and newlines survive |
| the exit status | every step is an `exec`, so no process sits between the coordinator and your shell |
| Ctrl-C | the interrupt reaches the coordinator, the shell sees 130, and nothing is left running inside the container |
| the environment | the shim assigns nothing and exports nothing. What the coordinator sees is what `devbox exec` gives it |

`devbox exec` is pinned to one environment on purpose. The coordinator is
installed in exactly one place, so the working directory decides which
repository it works on, and never where it runs. A repository that the router
would route to `rust-dev` still gets the coordinator from `web-dev`.

### The recursion guard

The shim refuses to run inside a container and exits 8. Two things make that
enough:

- the shim itself tests `/run/.containerenv`, `/.dockerenv` and
  `$DEVBOX_ACTIVE_ENV`
- the router strips the host `~/.local/bin` from the container `PATH`, so
  `agentqueue` inside `web-dev` is the real program, not the shim

Inside the container the direct call keeps working, and it is the same command:

```bash
devbox exec web-dev -- agentqueue plan --repo ~/projects/dkkb
```

### The exit codes a router adds

The shim can fail before the coordinator starts. Those failures come from the
router, and they do not collide with the coordinator exit codes in the table
below, except for the shared meaning of 2 (a usage error):

| Code | Meaning |
| --- | --- |
| 5 | the environment is not configured on this machine |
| 6 | the Distrobox container is missing |
| 8 | the shim was started inside a container |
| 127 | `agentqueue` is not installed inside the environment; run `bootstrap/web-dev.sh` |

### The runtime

`agentqueue` is written in Python with the standard library only, so it needs
nothing that the base system does not already provide. It calls
`<checkout>/bin/agentbox` directly, so the two halves can never be different
versions.

## Parallel runs

`maxParallel` above 1 works, and it is not the default. Two agents on one
repository share a base branch, and a merge by one invalidates the CI result of
the other. The scheduler only ever starts issues that do not block each other,
and each run takes its own branch, its own agentbox lock and its own run
directory.

A security failure sets a stop flag. Runs that are already inside `agentbox`
finish that call, and nothing is pushed or merged afterwards.

## Honest limits

- **The claim is best effort.** GitHub has no compare-and-swap on a label. Two
  coordinators that start in the same second agree on a winner through comment
  order, and a third-party tool that ignores the convention is not stopped by
  it.
- **A repository with no branch protection reports no required checks.** The
  policy names them instead, and `requireCiChecks` refuses a commit that
  reported no check at all. That is a fail-closed default and not a substitute
  for branch protection.
- The coordinator honours the target repository's git hooks. It is the user's
  own repository, and `agentbox` proves that its hooks did not change during a
  run.
- The pull request body says the branch was produced unattended. It does not
  make the change correct. Automatic merge is a statement about the gates, not
  about the work.
- A merge queue, a required approval or a `CODEOWNERS` rule will refuse the
  merge call. The queue reports that and asks for a human. It does not try to
  work around it.
- Nothing schedules a drain. `agentqueue drain` runs when a human starts it.
- **`kill -TERM` against the host process is not a clean stop.** Ctrl-C in the
  terminal is: `bin/devbox-verify` checks that the coordinator ends and that
  nothing survives inside the container. A `SIGTERM` sent to the host-side
  process id ends that process and leaves the coordinator running inside
  `web-dev`, because `podman exec` does not forward it. This is a property of
  `distrobox enter`, and it is the same for `devbox exec`, `devbox run` and the
  `claude` and `codex` shims. Stop a drain with Ctrl-C.

## Related documents

- [sandcastle.md](sandcastle.md) - the unattended agent and its boundary
- [architecture.md](architecture.md) - the whole machine
- [secrets.md](secrets.md) - what never enters a repository or a sandbox
