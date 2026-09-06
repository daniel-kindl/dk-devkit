# The repository name

This is the deliberate naming decision that #24 and #8 require, and the first
item on the #17 publication checklist. #24 asked for the name to be evaluated
*after* the architectural transition, so that the choice answers what the
repository is rather than what it was.

The decision below is a decision, not a preference. It states what the name has
to do, what each candidate costs, and what would reopen the question.

| | |
| --- | --- |
| Decided repository name | `daniel-kindl/dk-devkit` |
| Decision | **Renamed from `workstation` to `dk-devkit`.** |
| Decided on | 2026-09-06 |
| Owns this decision | #24, with the checklist item in #17 |
| Reopens when | one of the triggers below occurs |

The first evaluation, recorded the same day, chose to keep `workstation`. The
owner decided otherwise. The evaluation below is unchanged, because the costs
and the candidates it describes are still the facts; only the weighing changed,
and [the decision](#decision) records both.

## What the name has to do

The toolkit identity is real in the codebase now, so the name is judged against
the product, not the roadmap:

1. **Name the product.** Reusable components are primary. The complete personal
   workstation is one profile of the same components.
2. **Survive publication.** A public reader meets the name before the README.
3. **Not lie.** The repository must not claim a scope the tree does not have.
4. **Not cost more than it returns.** A rename is a real operation on a real
   machine, not only a field in GitHub.

## What a rename actually costs

The cost is small in the repository and larger on the machine.

**In the tree**, six tracked references name the repository:

| Reference | Where |
| --- | --- |
| Clone URL | `README.md`, `docs/recovery.md` |
| Issue link | `README.md` |
| Agent instructions heading | `AGENTS.md` |
| Vulnerability-reporting API path | `docs/public-release-audit.md` |
| Prose that names the repository | `bin/install-skills`, `lib/agentqueue/prompts.py` |

No script resolves the checkout by its directory name. Every entry point
derives `REPO_ROOT` from its own path, so the code does not care what the
directory is called.

**On the machine**, the checkout is load-bearing. `~/.local/bin` holds symlinks
into it, and so do `~/.agents`, the Claude and Codex configuration and the
status line. [architecture.md](architecture.md) states the same property. A
GitHub rename alone changes nothing there, because GitHub redirects the old
URL and a configured remote keeps working. Renaming the *checkout directory* to
match is what breaks the links, and it needs `bootstrap/host.sh` to run again.

So a rename is two operations that people tend to treat as one. The repository
half is cheap. The machine half is a converge step, and it fails quietly:
a dangling symlink breaks the router and the shared agent policy until the next
verification run reports it.

## The candidates

### Keep `workstation` (the first decision)

Accurate today, and honest about the evidence. Bazzite is the only platform with
verification results, and `daniel` is the only profile that describes a complete
machine. The name says "this is one person's machine, written down", which is
what a reader gets in addition to the components.

Against it: the name reads as a machine backup. A reader looking for
`agentbox` or `devbox` does not search for "workstation", and the name
undersells the part of the repository that is reusable.

### Rename to `devkit` or `dk-devkit` (the second decision, adopted)

`devkit` names the product model directly. It is also generic: the term is used
widely, it collides in search, and it says nothing about the security and
isolation boundaries that make `agentbox` and `agentq` worth reusing.

`dk-devkit` is unique. It reads as an owner prefix, which is accurate for a
personal toolkit and is what separates it from every other `devkit`.

Against both: neither is better than the description and topics field that #17
has to write anyway, if discovery is the only question. The argument that
carried is timing rather than discovery: the repository is private, so the
rename is nearly free today and never gets cheaper.

### Split the repository

Publish the reusable components separately and keep `workstation` as the
personal composition. This is the only option that fully resolves the tension in
the name.

Against it: it is a different piece of work. It multiplies the release surface,
the verification surface and the security review, and #24 explicitly prefers
incremental extraction over a big-bang change. Nothing about the current
architecture prevents it later.

## Decision

**Rename to `daniel-kindl/dk-devkit`.** Decided by the owner on 2026-09-06.

The reasoning:

1. **The name should name the product.** The toolkit identity is real in the
   codebase now. `workstation` names the composition, which is one profile of
   the components, and it is the part of the repository a reader is least
   likely to reuse.
2. **Before publication is the cheap moment.** The repository is still private.
   No external clone, link or reference exists to break, so the rename costs
   less now than at any later point.
3. **`dk-devkit` over `devkit`.** `devkit` is generic and collides in search.
   The `dk-` prefix makes it unambiguous, and this is one person's toolkit, so
   an owner prefix describes it rather than overreaching.
4. **The cost is bounded and known.** Six tracked references, listed above, plus
   the machine step below. GitHub redirects the old URL, so nothing breaks at
   the moment of the rename.

### What was decided first, and why it changed

The first evaluation chose to keep `workstation`. It weighed the rename against
an empty description field: #17 has to write a description and topics anyway,
and those carry the identity more directly than a name does. On that reading the
rename bought little and cost a converge step.

The owner weighed it differently, and reason 2 is the strongest argument for
deciding now rather than later: the window in which a rename is nearly free
closes at publication. That argument does not depend on the description field,
so it survives the objection the first decision was built on.

Both decisions are recorded because the reversal is the useful part. The cost
analysis above did not change; the weighing did.

### The machine step is done

The GitHub rename, the tracked references and the checkout directory are all
complete. `~/projects/workstation` is now `~/projects/dk-devkit`, and the 21
symlinks that point into the checkout were repointed with it: the `~/.local/bin`
commands, the `devbox` router configuration, and the agent home of each
development environment. The router's global assignment in `repos.tsv` moved
too.

The checkout stays load-bearing at the new path, so the property in
[architecture.md](architecture.md) is unchanged: delete it and the shared
policy, the status line and the router all break.

This closes the evaluation that #24 requires. It does not close the question.

## What reopens the question

The name now matches the product, so the pressure that produced this evaluation
is gone. Reopen the decision only when one of these becomes true:

- the components are split into their own repository, which leaves `dk-devkit`
  naming a composition rather than a kit;
- the repository stops being one person's toolkit, so the `dk-` prefix becomes
  wrong;
- the repository is public and `dk-devkit` is measured to be the discovery
  problem, with the description and topics from #17 already in place.

A rename after publication is not free. External links, clones and references
exist by then, and only the GitHub redirect protects them.

## How to rename safely, when that happens

Do these in order. Do not stop in the middle.

This is the order the `workstation` to `dk-devkit` rename followed.

1. Rename the repository on GitHub. The old URL redirects, so no clone breaks
   at this point. `verify.sh` module 10 starts failing here, on purpose: the
   remote and the recorded name no longer agree.
2. Update the tracked clone URL and the issue link. `verify.sh` module 10
   fails until the recorded name and the tracked URLs agree.
3. Update the recorded name in this file, and record why the question reopened.
4. Rename the checkout directory **only** if you want the paths to match. This
   is the step that breaks the installed symlinks.
5. Run `bootstrap/host.sh` again to relink, then `./verify.sh`. A dangling link
   is a failure, not a warning.
6. Update the remote of every other clone: `git remote set-url origin <new>`.
