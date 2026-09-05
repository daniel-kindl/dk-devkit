# Toolkit components

The toolkit installs **components**. A component is one reusable thing: a
command, a runtime, a development environment, or a composition of those. You
name the components you want, and the installer resolves everything they
declare and nothing else.

```bash
./install.sh --list                        # every component
./install.sh --dry-run --components web-dev
./install.sh --components agentbox
./install.sh --components daniel           # the complete personal workstation
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
  "summary": "Fedora Distrobox with an isolated home and the Node toolchain.",
  "requires": ["distrobox", "devbox"],
  "capabilities": ["linux", "host", "distrobox", "container-runtime"],
  "unattended": true,
  "install": ["components/web-dev/install.sh"],
  "doctor": null,
  "verify": ["./verify.sh", "--only", "2"],
  "manual": ["Sign in to Claude Code and Codex inside web-dev."],
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
| `group` | The heading `--list` prints it under. |
| `summary` | One sentence. |
| `requires` | Component identifiers this component depends on. |
| `capabilities` | Platform capabilities the **installation** needs. |
| `unattended` | Whether unattended installation is safe. |
| `install` | The command that converges the component, or `null`. |
| `doctor` | The command that reports readiness, or `null`. |
| `verify` | The command that verifies the component, or `null`. |
| `manual` | Actions only a human can complete. |
| `state.public` | Tracked configuration this component owns. |
| `state.local` | Machine-local or private state, which stays out of Git. |

Every operation is a plain executable. The installer runs it from the top of
the checkout, so a component can also be run by hand exactly as the installer
runs it:

```bash
components/devbox/install.sh --dry-run
```

Component-specific behaviour belongs in the component directory.
Platform-specific behaviour belongs behind the capability layer, not in the
component. Distribution adapters are issue #13.

### `install`, `doctor` and `verify`

- `install` must be idempotent. It checks the current state and changes only
  what does not match.
- `doctor` decides whether the component is already ready. A component with no
  `doctor` is always installed when it is selected.
- `verify` runs after installation, and only for the components the run
  selected.
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

A capability a component needs but the machine does not have blocks that
component, and everything that depends on it. The run then stops and names
them, rather than installing half a graph.

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
MANUAL ACTION
  Authenticate GitHub on the host: gh auth login --git-protocol ssh
```

## Options

| Option | Effect |
| --- | --- |
| `--list` | Print the catalogue and change nothing. |
| `--components a,b` | Install these components and what they declare. |
| `--dry-run` | Print the resolved plan and change nothing. |
| `--force` | Install a component again even when it is already ready. |
| `--no-verify` | Install without verifying. |

An interactive component picker and named `--profile` selection are issue #12.
Until then, a profile is selected the way any other component is:
`--components daniel`.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success, or a dry run that resolved. |
| 2 | Usage error, or a malformed manifest. |
| 3 | The selection cannot be resolved: unknown component, or a cycle. |
| 4 | A selected component is blocked by a missing capability. |
| 5 | A component installation failed. The message names the component. |
| 6 | Verification failed after installation. |

## Credentials

The installer collects no credential and writes no credential value. A
component that needs authentication declares it in `manual`, and the run
reports it as an action to complete before a re-run. `state.local` says where
the private state lives, which is always outside this repository.

## Profiles

A profile is a component of kind `profile`. It installs nothing; it only
declares what it composes.

`daniel` is Daniel's complete workstation. It is public and reproducible
because it holds only component choices, never a credential or a machine
identity.

```bash
./install.sh --dry-run --components daniel
```

Nothing depends on `daniel`. Every component it names is installable on its
own.

## Adding a component

1. `mkdir components/<id>` and write `component.json`.
2. Put the operations in the same directory, or point at a shared library
   function in `bootstrap/lib/` when the host bootstrap runs the same step.
3. Declare the capabilities the installation needs, not the distribution.
4. Add the component to the `daniel` profile only if Daniel's workstation has
   it.
5. `./verify.sh --only 15` checks the contract, the resolver and the tests.
