# dotnet-dev

`dotnet-dev` is the reusable .NET development environment. It supports C# and
keeps the SDK state in an isolated Distrobox home.

The environment provides:

- Fedora 44 in a Distrobox container;
- the .NET SDK, pinned in `manifests/dotnet-sdk.env`;
- GitHub and build tools;
- Claude Code, Codex and Grok after bootstrap;
- an isolated home at `~/.local/share/distrobox-homes/dotnet-dev`.

The repository owns the target framework and project dependencies through
`.csproj`, `.sln`, `global.json`, and related files.

## Why the SDK does not come from a package

A repository declares the SDK it needs in `global.json`, and that pin names a
**feature band**: `10.0.401` is band 4xx, `10.0.111` is band 1xx. Every
`rollForward` policy selects a version equal to or higher than the pin, and
none of them moves down a band. Fedora packages band 1xx only, so a repository
that pins band 4xx cannot build against `dotnet-sdk-10.0`, whatever
`rollForward` it sets.

`bootstrap/dotnet-dev.sh` therefore installs the upstream SDK that
`manifests/dotnet-sdk.env` pins, checks it against the published SHA-512
digest, and unpacks it into the container home. `~/.bashrc.d` puts it in front
of the distribution package, which stays installed as the fallback the
container starts with. `godot-dev` installs the same SDK from the same
manifest, through the same function in `bootstrap/lib/dotnet.sh`.

To move to another SDK, change `DOTNET_SDK_VERSION` and `DOTNET_SDK_SHA512`
together, then re-run the bootstrap. The digest is the published SHA-512 of the
`linux-x64` tarball, which the
[release index](https://github.com/dotnet/core/blob/main/release-notes/10.0/releases.json)
lists. The layout is side-by-side, so a new version is added and the older ones
stay in place for a `global.json` that still selects them.

## Install

```bash
./install.sh --components dotnet-dev
```

Create the container and run the bootstrap directly when needed:

```bash
distrobox assemble create --file distrobox/dotnet-dev.ini
devbox exec dotnet-dev --cwd ~/projects/dk-devkit -- ./bootstrap/dotnet-dev.sh
```

The router infers `dotnet-dev` for repositories with `.sln`, `.slnx`,
`.csproj`, `.fsproj`, or `global.json` files. A repository can also declare
`dotnet-dev` in `.devbox`.
