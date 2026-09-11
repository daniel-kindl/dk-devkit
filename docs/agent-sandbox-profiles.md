# Agent sandbox profiles

`agentq` remains a trusted coordinator in `web-dev`. A repository does not move
that authority into its language-specific Distrobox. It selects only the
disposable sandbox image that `agentbox` gives to Sandcastle.

## Profiles

| Profile | Image | Project toolchain |
| --- | --- | --- |
| `web` | `localhost/workstation/sandbox-web` | Node 22 and pnpm support |
| `python` | `localhost/workstation/sandbox-python` | `uv`; the repository selects Python |

The Python image does not pin one interpreter. `uv` reads `pyproject.toml`
and/or `.python-version` and installs the requested interpreter inside the
sandbox home. This keeps interpreter ownership in the project and keeps the
sandbox reusable.

## Selection

A repository can pin a profile with a tracked `.agentbox-profile` file:

```text
python
```

The file contains one profile name. Comments and blank lines are allowed.
Unknown profile names are refused.

When the file is absent, `agentq` uses conservative detection:

- a Python marker (`pyproject.toml`, `.python-version`, or `uv.lock`) with no web
  marker selects `python`;
- a repository with any web marker (`package.json` or a JavaScript lockfile)
  keeps `web`;
- everything else keeps `web` for backward compatibility.

A polyglot repository therefore never changes profile because a new file
appeared. Pin it explicitly when it needs another sandbox.

The profile maps to a local image reference pinned in
`manifests/sandcastle.env`. A repository cannot use `.agentbox-profile` to name
an arbitrary image.

## Build

Build one profile explicitly:

```bash
agent-sandbox build python
```

Use `--force` after changing its Containerfile or pinned version:

```bash
agent-sandbox build python --force
```

List the profiles:

```bash
agent-sandbox list
```

The historical `agentbox build` command still builds the runner and web
sandbox. Existing users and existing web repositories do not change behavior.

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
