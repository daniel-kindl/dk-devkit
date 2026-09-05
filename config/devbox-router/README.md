# devbox router

Routes host commands — in particular the `claude` and `codex` agent CLIs that
Orca launches — into the Distrobox development environment that owns the
current Git repository.

Everything here is workstation configuration. It deliberately lives outside any
project repository. The only per-project artefact this system understands is an
optional `.devbox` file, and using one is a project's own decision.

## Layout

    ~/.local/bin/devbox              the router + management CLI
    ~/.local/bin/devbox-verify       the verification suite
    ~/.local/bin/claude              host shim -> devbox agent claude
    ~/.local/bin/codex               host shim -> devbox agent codex
    ~/.local/bin/agentqueue          pinned shim -> devbox exec web-dev
    ~/.local/bin/devbox-run          compatibility wrapper -> devbox run
    ~/.local/bin/web-dev-run         compatibility wrapper -> devbox exec web-dev

    ~/.config/devbox-router/settings.env          global settings
    ~/.config/devbox-router/environments.d/*.env  one file per environment
    ~/.config/devbox-router/repos.tsv             repo -> environment assignments
    ~/.config/devbox-router/inference.tsv         automatic inference rules
    ~/.config/devbox-router/backups/              pre-migration copies of the old scripts

## Resolution precedence

1. `$DEVBOX_ENV`                       explicit override (testing, one-offs)
2. `<repo>/.devbox`                    committed, repo-local declaration
3. `<git-common-dir>/devbox-env`       per-clone, uncommitted declaration
4. `repos.tsv`                         global assignment
5. `inference.tsv`                     automatic, only when unambiguous
6. otherwise fail with guidance

Repositories are identified by
`git rev-parse --path-format=absolute --git-common-dir`, so every Git worktree —
including the ones Orca creates under `~/projects/.worktrees` — inherits its
primary checkout automatically. Worktrees must never be listed in `repos.tsv`.

Inference never overrides an explicit declaration or assignment, and
`devbox assign` refuses to change an existing assignment without `--force`.
A repository whose markers point at more than one environment fails (exit 7)
instead of picking one.

## Environment files

`environments.d/<name>.env`, `key = value`, comments with `#`:

    box              Distrobox container name          (default: the file name)
    workspace_host   host directory mounted into the box
    workspace_guest  where it is mounted inside the box (default /workspace)
    login_shell      1 = run through the box login shell (default 1)
    init_file        optional host script sourced inside the box before the command
    home             the box HOME (auto-detected from the container otherwise)
    description      free text

Toolchain setup belongs to the environment, not to the router. `web-dev` needs
no `init_file` because the container's own `~/.bashrc` loads nvm and
`login_shell = 1` picks that up. An environment that needs something else can
either configure its own shell rc inside the box or point `init_file` at a
script here.

Directories outside `workspace_host` are reached through `/run/host/<path>`,
which every Distrobox mounts, so nothing ever fails for being "outside the
workspace".

## Common tasks

    devbox where                     what environment does this directory use, and why
    devbox list                      environments, containers, assignments
    devbox assign web-dev ~/projects/foo
    devbox unassign ~/projects/foo
    devbox check                     do all configured containers exist
    devbox doctor                    full diagnostics for the current directory
    devbox exec web-dev -- pnpm i    run something in a named environment
    devbox run -- pnpm i             run something in this repository's environment
    devbox verify                    run the full verification suite

    devbox new-env rust-dev --box rust-dev --workspace ~/projects:/workspace
    devbox new-shim gemini           add a host shim for another agent CLI
    devbox new-shim aq --env web-dev add a host shim pinned to one environment
    devbox new-shim aq --print       print the shim text instead of writing it

Exit codes: 2 usage, 3 not a repository, 4 unresolved, 5 environment not
configured, 6 container missing, 7 ambiguous inference, 8 refused
(recursion guard / would silently change an assignment), 127 command not found
inside the container.

## Two kinds of host shim

A **resolved** shim asks the repository which environment owns it:

    exec "$router" agent claude "$@"

That is right for a toolchain command. `claude` in a Rust repository belongs in
`rust-dev`, and in a Node repository it belongs in `web-dev`.

A **pinned** shim names the environment:

    exec "$router" exec web-dev --cwd "$PWD" -- agentqueue "$@"

That is right for a command that is installed in exactly one environment. The
working directory still crosses the boundary, so a relative path such as
`--repo .` keeps its meaning; only the destination is fixed.

Both kinds refuse to run inside a container and exit 8, and the router strips
this directory from the container `PATH`, so a shim can never call itself.

## Orca

Orca finds bare `claude` and `codex` on `PATH` because the shims keep those
names in `~/.local/bin`. Each shim hands off to `devbox agent`, which resolves
the environment from the worktree, translates the working directory, and execs
the agent inside the container — so the agent and everything it spawns stay in
that environment.

Orca writes its Claude Code hooks and statusline into the *host*
`~/.claude/settings.json`, but Claude runs with the container's HOME. When
`orca_integration = 1` and Orca environment variables are present, the router
mirrors just the `hooks` and `statusLine` keys into the container's settings and
links the container's `~/.orca` to the host's. It records what it wrote in
`.devbox-orca-managed.json` and never overwrites a value that was changed by
hand. Codex needs none of this: Orca points `CODEX_HOME` at a host path that is
already bind-mounted into the box.
