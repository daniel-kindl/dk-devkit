# Contributing

This repository is Daniel's real development toolkit. It is intentionally opinionated, but reusable fixes, safer abstractions, platform ports, and focused tooling improvements are welcome when they preserve the repository's architecture and security boundaries.

## Before changing code

Prefer a focused issue and a focused pull request. Do not combine unrelated workstation preferences, architectural changes, and bug fixes in one change.

For reusable components:

- keep dependencies and required capabilities explicit;
- avoid introducing a dependency on the complete `daniel` workstation profile unless it is genuinely required;
- keep platform-specific package/runtime logic behind the platform/capability boundary where practical;
- preserve deterministic install/check/verify behavior;
- keep credentials and machine-local private state outside Git.

## Security-sensitive changes

Changes to `agentbox`, `agentq`, credential handling, import validation, secret scanning, sandbox creation, or host/container routing require extra care.

Do not weaken these properties merely to make a port easier:

- unattended model sandboxes do not receive GitHub or SSH authority;
- the real repository is not exposed to the unattended sandbox;
- imported agent work is validated before trusted GitHub operations;
- merge and CI/review gates fail closed when their state is uncertain.

Read `SECURITY.md` and the relevant architecture documentation before modifying these paths.

## Platform support

Do not claim support from code inspection alone. A platform/component combination should have reproducible verification evidence before documentation calls it supported.

Bazzite/Fedora is currently the primary verified implementation. Other platforms are being added through capability adapters rather than by duplicating the complete setup.

## Testing

Run the most focused verification that covers the change, then the broader suite when the environment supports it.

Typical commands include:

```bash
./verify.sh --list
./verify.sh --only <module>
./verify.sh
./verify.sh --full
```

Some checks require Daniel's real host/container environment. When a contributor cannot execute those checks, the pull request must say so rather than claiming they passed.

## Documentation

Technical prose follows the repository's ASD-STE100 policy in `config/agents/AGENTS.md`.

Document current behavior as current behavior. Mark planned component installers, profiles, platform adapters, or other roadmap features as planned until they exist and are verified.

## Pull requests

A useful pull request explains:

- what changed and why;
- the affected component or security boundary;
- the verification that was run;
- any verification that still needs the target workstation/platform;
- migration or compatibility effects for breaking changes.

Do not include credentials, private authentication state, or unrelated generated files.
