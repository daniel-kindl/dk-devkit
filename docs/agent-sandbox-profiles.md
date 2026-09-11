# Agent sandbox profiles

`agentq` remains a trusted coordinator in `web-dev`. A repository does not move
that authority into its language-specific Distrobox. It selects only the
disposable sandbox image that `agentbox` gives to Sandcastle.

## Profiles

| Profile | Image | Project toolchain |
| --- | --- | --- |
| `web` | `localhost/workstation/sandbox-web` | Node 22 and pnpm support |
| `python` | `localhost/workstation/sandbox-python` | `uv`; the repository selects Python |

`SANDBOX_PROFILES` in `manifests/sandcastle.env` is the list of profiles.
`agent-sandbox`, `agentbox` and `agentq` all read that list. Each profile has
an image pin in the manifest and a Containerfile in
`containers/sandbox-<profile>/`. The image must be a `localhost/` image.

The Python image does not pin one interpreter. `uv` reads `pyproject.toml`
and/or `.python-version` and installs the requested interpreter inside the
sandbox home. This keeps interpreter ownership in the project and keeps the
sandbox reusable.

Every profile copies the same credential shim, from
`containers/sandbox-web/bin/agent-cli-shim`. `agent-sandbox` passes that
directory to the build as the build context `shim`.

## Selection

`agentq` selects the profile once, before the queue starts. It reads the
working tree of the repository, and it never runs project code to do so.

A repository can pin a profile with a tracked `.agentbox-profile` file:

```text
python
```

The file contains one profile name. Comments and blank lines are allowed. The
file must be a regular file of at most 256 bytes. `agentq` refuses a symbolic
link, and it refuses an unknown profile name without repeating it.

When the file is absent, `agentq` uses conservative detection:

- A Python marker (`pyproject.toml`, `.python-version`, or `uv.lock`) at the
  repository root selects `python`, if no directory holds a project file of
  another toolchain.
- These are project files of another toolchain: `package.json`, a JavaScript
  lockfile, `bun.lock`, `bun.lockb`, `deno.json`, `deno.jsonc`,
  `tsconfig.json`, `Cargo.toml`, `go.mod`, `pom.xml`, `build.gradle`,
  `build.gradle.kts`, `Gemfile`, `composer.json`, `mix.exs`, and a `.csproj`,
  `.fsproj` or `.sln` file. One of them in any directory keeps `web`.
  Detection skips `node_modules`, `__pycache__`, `venv`, `site-packages`, and
  every directory whose name starts with `.`.
- Everything else keeps `web` for backward compatibility.

A repository with more than one toolchain stays on `web` until it pins a
profile explicitly. Detection reads a limited number of directory entries, and
a larger tree also keeps `web`.

An unusable `.agentbox-profile` is a policy error. `agentq run` and
`agentq plan` stop with exit code 3 before they process an issue.
`agentq doctor` shows the selected profile and its image.

## Build

Build one profile explicitly:

```bash
agent-sandbox build python
```

Use `--force` after changing its Containerfile or pinned version:

```bash
agent-sandbox build python --force
```

List the profiles and their images:

```bash
agent-sandbox list
```

The historical `agentbox build` command still builds the runner and web
sandbox. `agentbox doctor` also reports the image of each other profile. A
missing image of another profile does not make the machine unready, because
only a repository that selects that profile needs it. When a run finds its
sandbox image missing, `agentbox` names the command that builds it.

## Python repository example

A Python project can keep the execution policy in `.agentqueue.json` and the
runtime profile in `.agentbox-profile`:

```text
# .agentbox-profile
python
```

For a `uv` project, deterministic checks can be:

```json
{
  "checks": [
    "uv sync --all-groups --frozen",
    "uv run ruff check .",
    "uv run ruff format --check .",
    "uv run pyright",
    "uv run pytest"
  ]
}
```

The lifecycle stays the same:

```text
host command
  -> trusted agentq coordinator in web-dev
  -> agentbox control plane
  -> selected disposable sandbox
  -> validated agent/* branch
```

Only the last environment changes with the repository profile.
