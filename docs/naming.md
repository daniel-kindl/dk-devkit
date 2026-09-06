# The repository name

This is the deliberate naming decision that #24 and #8 require, and the first
item on the #17 publication checklist. #24 asked for the name to be evaluated
*after* the architectural transition, so that the choice answers what the
repository is rather than what it was.

The decision below is a decision, not a preference. It states what the name has
to do, what each candidate costs, and what would reopen the question.

| | |
| --- | --- |
| Decided repository name | `daniel-kindl/workstation` |
| Decision | **Keep the current name.** Do not rename before publication. |
| Decided on | 2026-09-06 |
| Owns this decision | #24, with the checklist item in #17 |
| Reopens when | one of the triggers below occurs |

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

**In the tree**, three tracked lines name the repository:

| Reference | Where |
| --- | --- |
| Clone URL | `README.md`, `docs/recovery.md` |
| Issue link | `README.md` |

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

### Keep `workstation`

Accurate today, and honest about the evidence. Bazzite is the only platform with
verification results, and `daniel` is the only profile that describes a complete
machine. The name says "this is one person's machine, written down", which is
what a reader gets in addition to the components.

Against it: the name reads as a machine backup. A reader looking for
`agentbox` or `devbox` does not search for "workstation", and the name
undersells the part of the repository that is reusable.

### Rename to `devkit` or `dk-devkit`

`devkit` names the product model directly. It is also generic: the term is used
widely, it collides in search, and it says nothing about the security and
isolation boundaries that make `agentbox` and `agentq` worth reusing.

`dk-devkit` is unique but reads as a namespace prefix, not a name.

Against both: neither is clearly better than the description and topics field
that #17 has to write anyway. An empty description is the reason the name is
carrying this weight, and #17's F9 remediation removes that reason.

### Split the repository

Publish the reusable components separately and keep `workstation` as the
personal composition. This is the only option that fully resolves the tension in
the name.

Against it: it is a different piece of work. It multiplies the release surface,
the verification surface and the security review, and #24 explicitly prefers
incremental extraction over a big-bang change. Nothing about the current
architecture prevents it later.

## Decision

**Keep `daniel-kindl/workstation`.**

The reasoning, in order:

1. **A rename does not buy discovery yet.** The repository is private. It has no
   description and no topics, and #17 already owns writing both. Those fields
   are where a reader learns what the repository is, and they can say
   "portable personal development toolkit" without touching the name.
2. **#24 says not to combine the rename with the refactor.** It sets the bar at
   a concrete benefit. Better shelf appeal, with the description still empty,
   is not one.
3. **The name is not inaccurate.** The repository does converge a workstation.
   The README states the toolkit identity in its first line, and the
   documentation index separates the toolkit from the `daniel` profile.
4. **The cost lands on the machine, not on GitHub.** The checkout is
   load-bearing, and the value of renaming does not cover a converge step whose
   failure mode is quiet.
5. **Publication is reversible on this point.** GitHub keeps redirecting the old
   URL after a rename, so deciding later costs no more than deciding now. The
   reverse is not true: a rename now must be undone if it turns out wrong.

This closes the evaluation that #24 requires. It does not close the question.

## What reopens the question

Reopen this decision when any of these becomes true:

- a reusable component is published or installed **from outside** this
  repository, so the name reaches a reader who wants no workstation;
- more than one platform reaches the `verified` support tier, so the name's
  "one machine" reading becomes wrong;
- the components are split into their own repository, which makes the remaining
  personal composition the only thing `workstation` has to name;
- the description and topics from #17 are in place and discovery is still the
  measured problem.

## How to rename safely, when that happens

Do these in order. Do not stop in the middle.

1. Rename the repository on GitHub. The old URL redirects, so no clone breaks
   at this point.
2. Update the tracked clone URL and the issue link. `verify.sh` module 10
   fails until the recorded name and the tracked URLs agree.
3. Update the recorded name in this file, and record why the question reopened.
4. Rename the checkout directory **only** if you want the paths to match. This
   is the step that breaks the installed symlinks.
5. Run `bootstrap/host.sh` again to relink, then `./verify.sh`. A dangling link
   is a failure, not a warning.
6. Update the remote of every other clone: `git remote set-url origin <new>`.
