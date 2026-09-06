# Toolkit components

The toolkit installs **components**. A component is one reusable thing: a
command, a runtime, a development environment, or a composition of those. You
name the components you want, and the installer resolves everything they
declare and nothing else.

```bash
./install.sh                               # pick on a terminal
./install.sh --list                        # every component
./install.sh --dry-run --components web-dev
./install.sh --components agentbox
./install.sh --profile developer           # a tracked component set
./install.sh --profile daniel              # the complete personal workstation
```

`bootstrap/host.sh` and `bootstrap/web-dev.sh` remain supported. Both entry
points call the same library functions, so they converge the same state. The
component installer is the one that can install a part.

## The component contract

Each component is a directory under `components/`. The directory name is the
component identifier, and `component.json` is the contract.

```json
{
  "version": 1,
  "id": "web-dev",
  "name": "web-dev environment",
  "kind": "environment",
  "group": "Development environments",
  "status": "supported",
  "summary": "Fedora Distrobox with an isolated home and the Node toolchain.",
  "requires": ["distrobox", "devbox"],
  "capabilities": ["linux", "host", "distrobox", "container-runtime"],
  "unattended": true,
  "install": ["components/web-dev/install.sh"],
  "doctor": null,
  "verify": ["./verify.sh", "--only", "2"],
  "manual": ["Sign in to Claude Code and Codex inside web-dev."],
  "environment": { "container": "web-dev", "ini": "distrobox/web-dev.ini", "...": "..." },
  "state": {
    "public": ["distrobox/web-dev.ini"],
    "local": ["~/.local/share/distrobox-homes/web-dev/"]
  }
}
```

| Field | Meaning |
| --- | --- |
| `id` | Stable identifier. It must equal the directory name. |
| `name` | Display name. |
| `kind` | `tool`, `runtime`, `environment`, `extras` or `profile`. |
| `status` | `supported` (the default) or `planned`. |
| `group` | The heading `--list` prints it under. |
| `summary` | One sentence. |
| `requires` | Component identifiers this component depends on. |
| `capabilities` | Platform capabilities the **installation** needs. |
| `unattended` | Whether unattended installation is safe. |
| `install` | The command that converges the component, or `null`. |
| `doctor` | The command that reports readiness, or `null`. |
| `verify` | The command that verifies the component, or `null`. |
| `manual` | Actions only a human can complete. |
| `state.public` | Tracked configuration this component owns, relative to this checkout. |
| `state.local` | Machine-local or private state, outside this checkout, which stays out of Git. |
| `environment` | Only for `kind: environment`. Read [environments.md](environments.md). |

Every operation is a plain executable. The installer runs it from the top of
the checkout, so a component can also be run by hand exactly as the installer
runs it:

```bash
components/devbox/install.sh --dry-run
```

Component-specific behaviour belongs in the component directory.
Platform-specific behaviour belongs behind the capability layer, not in the
component. A distribution adapter says how one platform supplies a capability;
read [platforms.md](platforms.md).

### Planned components

A component with `"status": "planned"` is a module boundary without an
installation. It declares what it will be, and it declares no `install` and no
`doctor`. The installer refuses to install one, whether it was selected or
required:

```console
$ ./install.sh --components dotnet-dev
install.sh: planned, so it cannot be installed yet: dotnet-dev
```

`--list` marks it `~`, the picker does not offer it, and no profile composes
it. The planned development environments are in
[environments.md](environments.md).

### `install`, `doctor` and `verify`

- `install` must be idempotent. It checks the current state and changes only
  what does not match.
- `doctor` decides whether the component is already ready. A component with no
  `doctor` is always installed when it is selected.
- `verify` runs after installation, and only for the components the run
  selected. It is the focused check that proves this component converged, so
  it names its own numbered module in `verify/`. Prefer a new module to a
  wider one: `./verify.sh --only <n>` then stays the focused answer, and one
  check never has two copies.
- A component with neither `install` nor `doctor` is a **composition**. It
  installs nothing of its own; a profile is the usual case.
- A component with a `doctor` but no `install` needs the platform to supply
  it. When its `doctor` fails, the run is blocked rather than guessing.

## Capabilities

`manifests/capabilities.json` declares what a platform can offer and how to
detect it. A component asks for capabilities; it does not ask for a
distribution.

```json
{
  "id": "container-runtime",
  "summary": "an OCI container runtime",
  "probe": {
    "kind": "any",
    "value": [
      { "kind": "command", "value": "podman" },
      { "kind": "command", "value": "docker" }
    ]
  }
}
```

| Probe kind | True when |
| --- | --- |
| `command` | The named command is on `PATH`. |
| `executable` | The named absolute path is executable. |
| `uname` | The kernel name matches. |
| `not-container` | The installer runs on the host, not in a container. |
| `any` | Any nested probe is true. |
| `platform` | Only the platform adapter can answer. |

A capability a component needs but the machine does not have blocks that
component, and everything that depends on it. The run then stops and names
them, rather than installing half a graph.

The platform adapter answers first. It can replace the generic probe with the
one that finds the capability on this platform, and it supplies the step a
human runs to obtain it. `manifests/platforms.json` holds every adapter, and
[platforms.md](platforms.md) explains the layer.

## Resolution

1. Detect the capabilities of this machine.
2. Discover the components in `components/*/component.json`.
3. Resolve the explicit selection.
4. Add every declared dependency, and record why it is there.
5. Order the result: dependencies first, ties broken on the identifier.
6. Show the plan.
7. Install in that order, stopping at the first failure.
8. Verify the selected components.

A dependency is installed because a component declared it, never because one
script happened to call another. The order is deterministic: the same
selection always produces the same order, whatever order you name it in.

A cycle is rejected before anything is installed.

```text
INSTALL
  agentq
  agentbox        required by agentq
ALREADY READY
  devbox
BLOCKED
  desktop-apps    missing capability: flatpak
ON THIS PLATFORM
  Bazzite ships Flatpak. Add the Flathub remote: flatpak remote-add ...
MANUAL ACTION
  Authenticate GitHub on the host: gh auth login --git-protocol ssh
```

## Options

| Option | Effect |
| --- | --- |
| `--list` | Print the catalogue and change nothing. |
| `--environments` | Print the development environment modules as TSV. |
| `--doctor` | Report the platform, its capabilities and the supported components. |
| `--hint cap` | Print how to obtain one capability on this platform. |
| `--state` | Report the public/local state boundary and change nothing. |
| `--components a,b` | Install these components and what they declare. |
| `--profile name` | Install what a tracked profile composes. |
| `--dry-run` | Print the resolved plan and change nothing. |
| `--force` | Install a component again even when it is already ready. |
| `--no-verify` | Install without verifying. |

`--profile` and `--components` can be combined. `--profile` accepts a profile
only, so a typo selects nothing unexpected; a profile can also be named as an
ordinary component with `--components daniel`.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success, or a dry run that resolved. |
| 2 | Usage error, or a malformed manifest. |
| 3 | The selection cannot be resolved: unknown component, or a cycle. |
| 4 | A selected component is blocked by a missing capability. |
| 5 | A component installation failed. The message names the component. |
| 6 | Verification failed after installation. |

## Public configuration and local state

Every component declares where its public configuration ends and where machine-
local state begins. The two sides never overlap.

```text
tracked reusable defaults  +  selected profile  +  optional local overrides
                           +  runtime discovery
                           =  effective configuration
```

`state.public` names tracked configuration this component owns. A public path
is relative to this checkout, so the same manifest describes the component on
every machine. It must not be absolute, must not start at the home directory,
and must not leave the checkout.

`state.local` names machine-local or private state. A local path starts at
`~/` or at an XDG variable, and it always resolves outside this checkout. It
must never name one machine's home directory, such as `/home/<user>/...`: a
declaration that does could only be true on the machine that wrote it.

The installer refuses a manifest that breaks either rule, so the boundary is a
rule and not a comment. `verify.sh` module 1b checks the tracked tree against
the same rules: every public path exists here, and no local path is tracked
here.

Read the boundary with `--state`. It reads the manifests only, so it touches
nothing on the machine:

```bash
./install.sh --state                        # every component
./install.sh --state --components web-dev   # that component and what it needs
./install.sh --state --profile daniel
```

```text
web-dev  (environment)
  public  distrobox/web-dev.ini
  public  manifests/web-dev-packages.txt
  local   ~/.local/share/distrobox-homes/web-dev/
  manual  Sign in to Claude Code and Codex inside web-dev; ...
```

Machine-local state stays out of Git even when it holds no secret. It is state
of one machine, and it has no meaning on another.
[not-tracked.md](not-tracked.md) records what was left out and why.

Installing a reusable component requires none of it. A local override is
optional, and a clean clone installs a component without one.

## Credentials

The installer collects no credential and writes no credential value. A
component that needs authentication declares it in `manual`, and the run
reports it as an action to complete before a re-run. `state.local` says where
the private state lives, which is always outside this repository.

## The picker

With no `--components` and no `--profile`, the installer opens a picker. It is
a plain prompt, not a full-screen program.

```text
Core tools
   3 [ ]   agent-home      Installs the shared agent policy, the status line...
   4 [ ]   agent-skills    Installs the skills in manifests/skills.tsv into...
   5 [x]   devbox          Routes an interactive command into the development...
Development environments
   6 [ ] ! distrobox       The container runtime every development environment...

  ! the machine is missing a capability this component needs

Select what to install. '?' explains the choices.
select>
```

| Input | Effect |
| --- | --- |
| `5` | Toggle that component. Several numbers on one line are allowed. |
| `web-dev` | Toggle a component, or a profile, by name. |
| `none` | Clear the selection. |
| Enter | Resolve the selection and show the plan. |
| `q` | Cancel and change nothing. |

Nothing is selected when the picker opens, and the plan is shown before the
question `Install this plan?`. Only an explicit `y` installs anything.

The picker opens **only on a terminal**. Without one, the installer prints what
it needs and exits 2, so an automated run never waits for an answer that cannot
arrive.

## Profiles

A profile is a component of kind `profile`. It installs nothing; it only
declares what it composes. A profile therefore expands the same way every time,
and `--profile minimal` resolves exactly what `--components minimal` resolves.

| Profile | What it composes |
| --- | --- |
| `minimal` | The `devbox` router and the shared agent policy. |
| `developer` | `minimal`, the third-party skills, and the development environments. |
| `agent-dev` | `developer`, plus `pi`, `agentbox`, `agentq` and `repo-labels`. |
| `daniel` | `agent-dev`, plus the host CLI tools and the desktop applications. |

Each profile contains the smaller one, so the four are one ladder rather than
four unrelated lists.

`daniel` is Daniel's complete workstation. It is public and reproducible
because it holds only component choices, never a credential or a machine
identity.

```bash
./install.sh --dry-run --profile daniel
```

No reusable component depends on a profile. Every component a profile names is
installable on its own.

## Adding a component

1. `mkdir components/<id>` and write `component.json`.
2. Put the operations in the same directory, or point at a shared library
   function in `bootstrap/lib/` when the host bootstrap runs the same step.
3. Declare the capabilities the installation needs, not the distribution. When
   the contract cannot express what the component needs, add the capability to
   `manifests/capabilities.json` first, and let an adapter answer for it.
4. Add the component to a profile only where that profile genuinely composes
   it. A reusable component must not depend on a profile.
5. Add the focused verification module and declare it as `verify`. The
   component then proves what it installed, and a reader who installs one
   component gets the evidence for it.
6. `./verify.sh --only 15` checks the contract, the resolver and the tests.
   `./verify.sh --only 16` checks the platform adapters, and
   `./verify.sh --only 17` checks the development environment modules.

A development environment declares one block more than this contract, and
[environments.md](environments.md) describes it.
