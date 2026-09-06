# Platform capabilities and adapters

A toolkit component never asks for a distribution. It asks for a **capability**,
and a **platform adapter** says how this machine supplies that capability.

```text
reusable components
        |
capability contract        manifests/capabilities.json
        |
platform adapters          manifests/platforms.json
  +-- Bazzite
  +-- Fedora
  +-- Debian or Ubuntu
  +-- Arch Linux
  `-- macOS
```

Distribution knowledge lives in `manifests/platforms.json` and nowhere else.
That keeps a component installable on every platform that can supply what the
component declares, and it keeps one platform fact in one place.

## The report

`./install.sh --doctor` reports the platform, the capabilities and the
components. It changes nothing, so it is safe to run on any machine.

```text
Platform
  Linux x86_64
  Bazzite (fedora family), verified
  The primary platform. Every component is verified here.

Capabilities
  ok  distrobox          the distrobox command
  --  homebrew           the Homebrew package manager
                         Install Homebrew on Bazzite: run "ujust install-brew", ...

Components
  ok  web-dev
  --  host-cli-tools     missing capability: homebrew
```

A component is `--` when this machine lacks a capability the component
declares, or when something the component requires is itself unsupported. One
unsupported component never hides another, and it never blocks an unrelated
supported one.

## Capabilities

`manifests/capabilities.json` declares every capability a component may ask
for. Each one carries a probe that finds it.

| Probe kind | Matches when |
| --- | --- |
| `command` | the named command is on `PATH` |
| `executable` | the named path is executable |
| `uname` | the kernel name equals the value |
| `not-container` | the installer runs on the host |
| `any` | any nested probe matches |
| `platform` | only the platform adapter can answer |

A `platform` probe means the generic answer does not exist. `package-manager`
is one: no single command names the system package manager on every platform,
so the adapter names it. A capability with a `platform` probe that no adapter
provides is a configuration error, and the installer refuses to run.

## Adapters

`manifests/platforms.json` lists the platforms in match order. The first
adapter that matches wins, so a derivative comes before the family it derives
from: Bazzite also reports `ID_LIKE=fedora`, and Bazzite is listed first.

```json
{
  "id": "fedora",
  "name": "Fedora",
  "family": "fedora",
  "support": "supported",
  "note": "The same family as the primary platform, but not verified here.",
  "detect": { "kind": "os-release", "ids": ["fedora"], "id_like": ["fedora"] },
  "provides": { "package-manager": { "kind": "command", "value": "dnf" } },
  "hints": { "distrobox": "sudo dnf install distrobox" }
}
```

| Field | Meaning |
| --- | --- |
| `id` | Stable identifier. |
| `name` | Display name. |
| `family` | The distribution family, for the report. |
| `support` | `verified`, `supported`, `experimental` or `unsupported`. |
| `note` | One sentence the report prints. |
| `detect` | `os-release` with `ids` and `id_like`, or `uname` with a kernel name. |
| `provides` | A capability, and the probe that finds it **on this platform**. |
| `hints` | A capability, and the one step that obtains it on this platform. |

`provides` replaces the generic probe. Homebrew is the example: the generic
probe looks in `/home/linuxbrew`, and the macOS adapter looks in
`/opt/homebrew` instead.

`hints` is what a human reads when a component is blocked. The installer prints
the hint under `ON THIS PLATFORM`, and `--doctor` prints it beside the missing
capability.

An adapter may only name a capability that `manifests/capabilities.json`
declares, and it may not answer with another `platform` probe.

## Support tiers

| Platform | Tier | What it means |
| --- | --- | --- |
| Bazzite | `verified` | The primary platform. `./verify.sh` passes here. |
| Fedora | `supported` | The same family. Not verified on this machine. |
| Debian, Ubuntu | `experimental` | The next family that must prove the abstraction. |
| Arch Linux | `experimental` | Follows Debian. |
| macOS | `unsupported` | No component is verified here. |

A tier is a statement about evidence, not a gate. The installer still resolves
capabilities on every platform, and a component that a machine can supply is
still installable there. A component whose capabilities the machine cannot
supply is reported as blocked before anything is installed, not after.

Windows is not an adapter. WSL2 comes first, and the report says when it runs
under WSL because no component is verified there.

`agentbox` depends on rootless Podman and on the isolation properties that
`docs/sandcastle.md` describes. Another OCI runtime is not interchangeable
merely because it runs containers. A new backend must prove those properties
before `agentbox` claims support on it.

## Asking from a shell

`bootstrap/lib/platform.sh` asks the same question the installer asks, so one
platform fact never has two copies.

```bash
. "$REPO_ROOT/bootstrap/lib/platform.sh"
hint=$(platform_hint "$REPO_ROOT" homebrew || true)
```

It calls `install.sh --hint <capability>`, which prints the step for the
detected platform, or exits non-zero when no adapter matches or the platform
declares no hint.

## Adding a platform

1. Add the adapter to `manifests/platforms.json`, before the family it derives
   from if it is a derivative.
2. Give it a `detect` rule, the `provides` probes that differ from the generic
   ones, and a `hints` entry for every capability a human must obtain by hand.
3. Set `support` to what the evidence allows. `verified` needs a passing
   `./verify.sh` on that platform.
4. Run `./verify.sh --only 16`.

Do not add a distribution check to a component. If a component needs something
the capability contract does not express, add the capability first.
