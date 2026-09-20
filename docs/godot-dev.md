# godot-dev

`godot-dev` is the reusable game development environment. It holds the Godot
engine and the C# toolchain together in one isolated Distrobox home.

The environment provides:

- Fedora 44 in a Distrobox container;
- the Godot engine, .NET build, pinned in `manifests/godot-dev.env`;
- the .NET SDK for C#, pinned in `manifests/dotnet-sdk.env`;
- the graphics, input, sound and font libraries the editor needs to open a
  window;
- GitHub and build tools;
- Claude Code and Codex after bootstrap;
- an isolated home at `~/.local/share/distrobox-homes/godot-dev`.

The repository owns the target framework and the project dependencies through
`project.godot`, `.csproj`, `.sln` and related files.

## Why the engine does not come from a package

The distribution package is the **standard** build of Godot, which has no C#
support. C# needs the **.NET** build, which upstream publishes as `mono`. So
`bootstrap/godot-dev.sh` installs the upstream release, checks it against the
SHA-512 digest that `manifests/godot-dev.env` pins, and unpacks it into the
container home. Change the version in the manifest, change the digest with it,
and re-run the bootstrap.

Godot 4.7 generates `net8.0` projects. The pinned SDK restores the `net8.0`
reference pack from NuGet on the first build, so the first build of a project
needs the network.

## Why the SDK does not come from a package either

A repository declares the SDK it needs in `global.json`, and that pin names a
**feature band**: `10.0.401` is band 4xx, `10.0.111` is band 1xx. Every
`rollForward` policy selects a version equal to or higher than the pin, and
none of them moves down a band. Fedora packages band 1xx only, so a repository
that pins band 4xx cannot build against `dotnet-sdk-10.0` at all.

`bootstrap/godot-dev.sh` therefore installs the upstream SDK that
`manifests/dotnet-sdk.env` pins, checks it against the published SHA-512
digest, and unpacks it into the container home. `~/.bashrc.d` puts it in front
of the distribution package, which stays installed as the fallback the
container starts with. Change the version in the manifest, change the digest
with it, and re-run the bootstrap.

The `godot` command is a launcher, not a symlink, for the same reason. The
editor builds C#, and the host application menu starts it through
`distrobox-enter`, which runs a command **without** a login shell. The launcher
sets `DOTNET_ROOT` and `PATH` itself, so the editor and a terminal build with
the same SDK.

## Install

```bash
./install.sh --components godot-dev
```

Create the container and run the bootstrap directly when needed:

```bash
distrobox assemble create --file distrobox/godot-dev.ini
devbox exec godot-dev --cwd ~/projects/dk-devkit -- ./bootstrap/godot-dev.sh
```

## The editor

The bootstrap installs `godot` as a command inside the container and exports a
desktop entry to the host application menu, so the editor starts from the menu
or from a shell in the box:

```bash
devbox exec godot-dev --cwd ~/projects/my-game -- godot --editor .
```

The editor draws through the host GPU. Distrobox passes the graphics devices
and the display socket through on its own, so nothing here configures them.

Headless runs work the same way, which is what an agent or a CI step uses:

```bash
devbox run -- godot --headless --path . --quit
devbox run -- dotnet build
```

## Export templates

An export needs the templates, which are a 1.2G download. The bootstrap reports
the step instead of doing it, so an install never pays for it. Install them
inside the box, once per engine version:

```bash
devbox exec godot-dev --cwd ~/projects/dk-devkit -- bash -c '
  . manifests/godot-dev.env
  tag=$GODOT_VERSION-$GODOT_RELEASE
  file=Godot_v${tag}_${GODOT_FLAVOR}_export_templates.tpz
  curl -fL -o /tmp/$file \
    https://github.com/godotengine/godot/releases/download/$tag/$file
  printf "%s  %s\n" "$GODOT_TEMPLATES_SHA512" "/tmp/$file" | sha512sum -c -
  mkdir -p "$HOME/.local/share/godot/export_templates"
  rm -rf "$HOME/.local/share/godot/export_templates/${GODOT_VERSION}.${GODOT_RELEASE}.${GODOT_FLAVOR}"
  unzip -q /tmp/$file -d /tmp/templates-$tag
  mv /tmp/templates-$tag/templates \
     "$HOME/.local/share/godot/export_templates/${GODOT_VERSION}.${GODOT_RELEASE}.${GODOT_FLAVOR}"
  rm -rf /tmp/$file /tmp/templates-$tag
'
```

The editor also installs them through **Editor > Manage Export Templates**,
which downloads the same archive.

## Routing

The router infers `godot-dev` from `project.godot`. That marker is **specific**:
a Godot C# repository also holds a `.csproj` and a `.sln`, which are
`dotnet-dev` markers, and a specific marker outranks the general markers of
another environment. `docs/environments.md` describes the tier.

A repository can also declare `godot-dev` in `.devbox`.

## Verify

```bash
./verify.sh --only 21
```
