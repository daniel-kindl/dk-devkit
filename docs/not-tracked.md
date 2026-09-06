# What this repository does not track, and why

Every entry below was inspected on the live machine and left out on purpose.

## Credentials and authentication state

`~/.ssh/id_ed25519`, `~/.config/gh/hosts.yml`, `~/.claude/.credentials.json`,
`~/.claude.json`, `~/.codex/auth.json`, `~/.gnupg/`, `~/.pki/`.

A restore cannot reproduce authentication, and a repository is the wrong place
to attempt it. See [secrets.md](secrets.md).

## Agent runtime state

`~/.claude/sessions/`, `~/.claude/history.jsonl`, `~/.claude/shell-snapshots/`,
`~/.claude/paste-cache/`, `~/.claude/session-env/`, `~/.codex/*.sqlite`,
`~/.codex/sessions/`, `~/.codex/models_cache.json`, `~/.codex/installation_id`,
`~/.claude/plugins/known_marketplaces.json`, `~/.local/state/skills/.skill-lock.json`.

This is per-session state. It has no value on another machine, and some of it
holds conversation content.

## Orca runtime state

`~/.orca/agent-hooks/`, `~/orca/workspaces/`, `~/.cache/orca/`,
`~/AppImages/orca.appimage`, and the `hooks` block that Orca writes into
`~/.claude/settings.json`.

Orca generates all of it, and the hook commands embed absolute machine paths.
Orca rewrites them when it starts. `bootstrap/*.sh` never touches the `hooks`
key, and `verify.sh` checks that the key survived.

## Toolchain payloads

`~/.config/nvm/` (the nvm checkout and every installed Node), `node_modules/`,
`~/.local/share/pnpm/store`, `~/projects/.pnpm-store`,
`~/.local/share/claude/versions/`, `~/.codex/packages/`, `~/.vscode-server/`.

These are large, and every one is reproducible from
`manifests/toolchain.env`. The repository pins the versions, not the bytes.

## Third-party skill content

`~/.agents/skills/*`, 43 skills from four upstream repositories.

`manifests/skills.tsv` records the source repository, the ref and the path for
each one. `bin/install-skills` fetches them and copies only the skill directory.
A dry run against the live store reproduces all 43 skills byte for byte, so
vendoring them would add weight and no fidelity.

`~/.agents/third-party-skills.tsv` is the generated provenance record that
`bin/install-skills` writes, including the resolved commit of each source. It is
generated state, so it is not tracked.

## Backlog coordinator state

`~/.local/share/agentqueue/`, which holds the generated prompts, the agentbox
run logs and the per-issue locks, and
`~/.config/agentqueue/repos/`, which holds a machine-local queue policy for a
repository that cannot carry `.agentqueue.json` yet.

None of it holds a credential. The prompts are generated from GitHub issues,
and a new run regenerates them. A queue policy that a repository **can** carry
belongs in that repository, as a tracked `.agentqueue.json`.

`~/.local/bin/agentq` on the host is generated too. `bootstrap/host.sh`
writes it with `devbox new-shim agentq --env <environment>
--map-path <option> --print`, from the two values `manifests/agentqueue.env`
names, so the router is the one source of truth for its text and this
repository tracks the generator rather than the result.

## Machine-specific router state

`~/.config/devbox-router/repos.tsv`.

The live file assigns one absolute host path, the expansion of
`~/projects/dkkb`, to `web-dev`. That path exists on one machine only.

It is also unnecessary. `dkkb` has a `package.json`, and `inference.tsv` already
resolves a `package.json` to `web-dev`. The repository therefore tracks the
generic inference rules and ships `repos.tsv.template`, which is empty.
`bootstrap/host.sh` installs the template only when no `repos.tsv` exists, and
never overwrites live assignments.

If you want the explicit assignment back after a restore, run:

```bash
devbox assign web-dev ~/projects/dkkb
```

The existing `devbox-verify` suite expects that assignment: its check A3 asserts
that the source is `global`, not `inferred`.

`~/.config/devbox-router/backups/` is generated, so it is not tracked either.

## Credential helpers that embed a session path

The container `~/.gitconfig` contains a credential helper written by the VS Code
Remote Containers extension. It points at a file under `/tmp` whose name is
unique to one session:

    helper = "!f() { .../node /tmp/vscode-remote-containers-<uuid>.js ...; }; f"

It is dead on any other machine and on any later session. The repository tracks
no `.gitconfig`. Git identity is a personal setting, and `verify.sh` only checks
that a `user.email` is configured, not what it is.

## Base system packages

`git` and `jq` on the host.

Both ship in the Bazzite image. `rpm-ostree status` shows no layered package on
this machine. `manifests/homebrew.txt` therefore lists only what this
workstation adds on purpose, and no Homebrew dependency that Homebrew resolves
by itself.

## Repository worktrees

`~/projects/.worktrees/`.

Orca creates and removes these. They resolve through the git-common-dir rule,
so they need no configuration at all.
