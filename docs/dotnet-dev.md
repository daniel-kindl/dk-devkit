# dotnet-dev

`dotnet-dev` is the reusable .NET development environment. It supports C# and
keeps the SDK state in an isolated Distrobox home.

The environment provides:

- Fedora 44 in a Distrobox container;
- the .NET 10 SDK;
- GitHub and build tools;
- Claude Code and Codex after bootstrap;
- an isolated home at `~/.local/share/distrobox-homes/dotnet-dev`.

The repository owns the target framework and project dependencies through
`.csproj`, `.sln`, `global.json`, and related files.

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
