# Agent skills

`agent-skills` installs one curated set of third-party skills into the canonical
store at `~/.agents/skills`. The toolkit owns the selection and the source
references. It does not vendor upstream skill content.

The resolver has two inputs:

- `manifests/skill-packs.tsv` declares each upstream repository, ref and root.
- `manifests/skill-profiles/<name>.tsv` selects exact skill directories from
  those packs.

A profile is an allowlist. A new skill that appears upstream does not install
until this repository selects it.

## Default composition

The `default` profile combines Matt Pocock's skills and pstack without two
owners for the same workflow stage.

Matt's skills own planning and problem shaping: grilling, domain modeling,
architecture surveys, specifications, tickets, triage, handoff and teaching.
pstack owns execution: implementation playbooks, debugging, TDD, verification,
parallel review and PR execution.

The profile keeps Matt's `teach` and pstack's `tdd`. It does not select the
other provider's version of those skills. pstack principle skills stay in the
profile because `poteto-mode` can refer to them during execution.

The profile also keeps the independent skills from ASD-STE100, Orca, Vercel
Skills and Humanizer.

## Commands

Resolve without network access:

```bash
bin/install-skills --resolve
```

The output is tab-separated and has these columns:

```text
name    source    ref    path    pack
```

List profiles:

```bash
bin/install-skills --list-profiles
```

Install the default profile:

```bash
bin/install-skills
```

Install one selected skill:

```bash
bin/install-skills tdd
```

Check the local store without network access:

```bash
bin/install-skills --check
```

Preview convergence or pruning:

```bash
bin/install-skills --dry-run
bin/install-skills --dry-run --prune
```

`--prune` removes only skill directories that are not in the selected profile.
It does not run when individual skill names are supplied.

## Machine-wide convergence

Each development environment has an isolated home, so one normal install changes
only the current `$HOME`. Run machine-wide operations from the host.

Preview the default profile across the host and every existing supported
environment:

```bash
bin/install-skills --whole-machine --dry-run --prune
```

Converge the whole machine:

```bash
bin/install-skills --whole-machine --prune
```

Check every store without changing it:

```bash
bin/install-skills --whole-machine --check
```

Use `--all-environments` instead of `--whole-machine` when the host store must
stay unchanged.

The command discovers environments from `bin/toolkit-install --environments`.
It does not contain an environment-name list. Only supported environments whose
isolated home already exists are entered. Missing environments are reported and
skipped. Each environment is entered through `devbox exec`, so the existing
router owns host-to-container path mapping and the container boundary.

Machine-wide dispatch rejects `--resolve`, `--list-profiles`, and
`SKILLS_MANIFEST` overrides. Those operations either do not depend on a home or
can name a host-only path that is not safe to reuse across isolated homes.

## Add or change a pack

Add one row to `manifests/skill-packs.tsv`:

```text
pstack    cursor/plugins    main    pstack/skills
```

Use a commit SHA instead of a branch when the source must be pinned. A profile
then selects exact directories relative to the pack root:

```text
poteto-mode    pstack    poteto-mode
tdd            pstack    tdd
```

A final skill name can occur only once in a profile. Resolution fails before
network access if two rows select the same name, if a pack is unknown, or if a
path is invalid. This makes provider choice explicit instead of depending on
install order.

## Compatibility

`SKILLS_MANIFEST=/path/to/file.tsv bin/install-skills` still accepts the old
four-column explicit manifest format:

```text
name    source    ref    path
```

Use this only for temporary or external manifests. The tracked toolkit state is
the pack and profile model above.

After a successful install, `bin/sync-agent-skills` refreshes the Claude and
Codex views of the canonical store. The generated provenance file at
`~/.agents/third-party-skills.tsv` records the source, requested ref, resolved
commit, install date and pack for each selected skill.
