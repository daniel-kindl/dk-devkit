# Development environment modules

A development environment is a toolkit component of kind `environment`. It is a
container with one purpose, an isolated home, and one language toolchain.

The environment **module** is `components/<id>/`. It declares the container, the
files that install it, and the router markers it owns. Nothing outside the
module holds a list of environment names, so adding an environment is adding a
module.

```bash
./install.sh --components web-dev      # one environment, and what it needs
./install.sh --environments            # every module, as TSV
```

## The environments

| Environment | Status | Toolchain |
| --- | --- | --- |
| `web-dev` | supported | Node and pnpm, through nvm, plus the agent CLIs |
| `python-dev` | supported | Python and uv |
| `golang-dev` | supported | Go and the Go module toolchain |
| `rust-dev` | supported | Rust and cargo, through rustup |
| `dotnet-dev` | planned | .NET |
| `android-dev` | supported | Android SDK, JDK 25 and Gradle wrapper |

A **planned** module is a boundary without an installation. It declares the
container name and the router markers, and nothing else. The installer refuses
to install one, and no profile composes one:

```console
$ ./install.sh --components dotnet-dev
install.sh: planned, so it cannot be installed yet: dotnet-dev
```

The router still resolves a planned environment from its markers. A .NET
repository therefore gets `dotnet-dev is not configured` rather than
`no environment could be resolved`, which is the more useful answer.

## The environment block

`component.json` carries the ordinary component contract, plus one block that
only an environment declares.

```json
{
  "id": "web-dev",
  "kind": "environment",
  "status": "supported",
  "requires": ["distrobox", "devbox"],
  "install": ["components/web-dev/install.sh"],
  "environment": {
    "container": "web-dev",
    "ini": "distrobox/web-dev.ini",
    "packages": "manifests/web-dev-packages.txt",
    "toolchain": "manifests/toolchain.env",
    "bootstrap": "bootstrap/web-dev.sh",
    "router": "config/devbox-router/environments.d/web-dev.env",
    "inference": "components/web-dev/inference.tsv",
    "home": "~/.local/share/distrobox-homes/web-dev/"
  }
}
```

| Field | Meaning |
| --- | --- |
| `container` | The Distrobox container name. |
| `ini` | The `distrobox assemble` definition that creates the container. |
| `packages` | The base packages the container image installs. |
| `toolchain` | The verified toolchain versions the in-container bootstrap reads. |
| `bootstrap` | The script that converges the toolchain inside the container. |
| `router` | The router environment file: box, workspace mapping, login shell. |
| `inference` | The router markers this environment owns. |
| `home` | The isolated container home. It is machine-local state. |

A planned module declares `container` and `inference` only. A supported module
declares all of them, and verification fails when a declared path is missing.

## Router markers

`components/<id>/inference.tsv` holds the markers of one environment:

```tsv
web-dev	package.json
web-dev	pnpm-workspace.yaml
```

`bootstrap/lib/devbox.sh` assembles every module's file into
`~/.config/devbox-router/inference.tsv`. That file is generated, not linked into
the checkout, because several modules own it together.

`bin/devbox` carries the same table as a fallback, for a host whose
configuration is not installed yet. `verify.sh --only 5` fails when the two
disagree, so the module stays the source of truth.

Markers must not overlap between environments. When the markers of two
environments both match a repository, the router fails with exit code 7 instead
of guessing.

## Adding an environment

1. `mkdir components/<id>` and write `component.json` with the environment
   block. Start at `"status": "planned"` and declare `container` and
   `inference` only.
2. Write `components/<id>/inference.tsv`. Every line names `<id>`.
3. Add the same rules to the fallback table in `bin/devbox`, in module order.
4. When the environment becomes real, add the container definition, the package
   manifest, the toolchain manifest, the in-container bootstrap and the router
   environment file, declare each of them in the block, and set
   `"status": "supported"`.
5. Add the component operations: `install` creates the container and converges
   the toolchain, and `verify` names the verification module.
6. `./verify.sh --only 17` checks the modules. `./verify.sh --only 5` checks the
   router configuration they produce.

Nothing else changes. `bootstrap/host.sh` creates the container of every
supported module, and the router installation links the environment file of
every supported module.

## What stays outside the module

- The isolated container home. It is machine-local state; `docs/not-tracked.md`
  says why.
- Repository assignments in `~/.config/devbox-router/repos.tsv`. They are
  absolute host paths.
- Distribution facts. An environment asks for the `distrobox` and
  `container-runtime` capabilities; `docs/platforms.md` says how a platform
  supplies them.
