# dk-devkit

`dk-devkit` is a portable toolkit for development environments, agent tools,
and reusable workflows. Install the components you need. Daniel's Bazzite
workstation is one profile of the toolkit.

Bazzite is the only verified platform. The installer uses each component's
declared capabilities to report what the current platform can install.
Read the [platform support guide](docs/platforms.md) for the support tiers.

## Get started

Clone the repository, list the available components, and install the ones you
need:

```bash
git clone https://github.com/daniel-kindl/dk-devkit.git
cd dk-devkit
./install.sh --list
./install.sh --components web-dev
```

Replace `web-dev` with a component ID from the list. Use `--dry-run` to preview
the installation plan. Read the [component guide](docs/components.md) for
dependencies, profiles, and local state.

Named profiles provide ready-made component sets: `minimal`, `developer`,
`agent-dev`, and `daniel`. The `daniel` profile describes the complete personal
workstation.

## Main commands

| Command | Purpose | Guide |
| --- | --- | --- |
| `./install.sh` | Lists components, reports requirements, and installs selections. | [Components](docs/components.md) |
| `devbox` | Runs commands in the development environment for a repository. | [Router](config/devbox-router/README.md) |
| `agentbox` | Runs an unattended agent against a disposable clone. | [Agent sandbox](docs/sandcastle.md) |
| `agentq` | Coordinates GitHub issue work and trusted GitHub operations. | [Agent queue](docs/agentq.md) |

The component list also includes Pi, `winbox`, repository tools, and seven
development environments. Run `./install.sh --list` to see all available
components. Read the [environment guide](docs/environments.md) for the
development environments.

## How the toolkit fits together

Each component declares its dependencies and required platform capabilities.
The installer resolves those requirements and installs the selected
components. Platform adapters describe how each platform supplies a
capability. Read the [architecture guide](docs/architecture.md) for the
workstation design.

`devbox` routes interactive commands to a long-lived development environment.
`agentbox` runs unattended work in a disposable clone and validates its result
before import. The sandbox does not receive GitHub or SSH authority. `agentq`
holds GitHub authority in the trusted layer and manages agent branches. Read
[SECURITY.md](SECURITY.md) for the trust boundaries.

## More information

- [Documentation index](docs/README.md)
- [Whole-workstation recovery](docs/recovery.md)
- [Contributing](CONTRIBUTING.md)
- [License](LICENSE)
