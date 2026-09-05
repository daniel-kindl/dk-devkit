# python-dev

`python-dev` is the reusable Python development environment. It is not tied to a single repository. T1Pal is the first intended consumer.

## Boundary

The container provides the development capability:

- Fedora 44;
- isolated HOME at `~/.local/share/distrobox-homes/python-dev`;
- host `~/projects` mounted at `/workspace`;
- Git/GitHub tooling;
- SQLite CLI;
- a small native-build baseline;
- pinned `uv`;
- Claude Code and Codex for interactive development;
- the shared agent policy, skills, status line, and Orca bridge.

A project provides its own Python/application state:

- Python version (`requires-python` and/or `.python-version`);
- `pyproject.toml`;
- `uv.lock`;
- virtual environment;
- application and test dependencies.

Do not add Pydantic, SQLAlchemy, Polars, NumPy, SciPy, scikit-learn, FastAPI, PyTorch, or other project libraries to the container manifest merely because one Python project needs them.

## Create and bootstrap

The host bootstrap creates the container when it is absent and registers the router definition:

```bash
./bootstrap/host.sh
```

Then bootstrap the isolated container HOME:

```bash
devbox exec python-dev --cwd ~/projects/workstation -- ./bootstrap/python-dev.sh
```

Authentication is manual per isolated HOME:

```bash
devbox exec python-dev -- gh auth login --git-protocol ssh
devbox exec python-dev -- claude
devbox exec python-dev -- codex login
```

The SSH private key is not copied into the container. Distrobox exposes the host ssh-agent socket instead.

## Python ownership

`manifests/python-dev.env` pins `uv`, but it intentionally has no `PYTHON_VERSION`.

A project can pin its interpreter, for example:

```text
.python-version
3.14
```

`uv` can then select or install that Python into the isolated `python-dev` HOME. This keeps the reusable container independent from any one project's runtime version.

## Routing

The router knows these Python markers:

```text
pyproject.toml
uv.lock
.python-version
```

When exactly one environment family matches, `devbox` can infer `python-dev`. A repository can always make the choice explicit with a tracked `.devbox` file containing:

```text
python-dev
```

If a repository matches Python and another environment at the same time, such as `pyproject.toml` plus `package.json`, automatic inference remains ambiguous and `devbox` refuses to guess. Add an explicit repository declaration when that is intentional.

## Verification

After bootstrap:

```bash
./verify.sh --only 25
```

The focused module checks the container image and HOME boundary, package-manifest parity, `uv`, project-owned Python policy, routing declarations, interactive agent clients, shared agent wiring, and SSH-agent exposure without printing key material.
