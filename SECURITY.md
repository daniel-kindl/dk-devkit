# Security policy

## Scope

This repository contains development tooling and automation with different trust levels. Security reports are especially important for changes that affect:

- `agentbox` sandbox creation, disposable clones, import validation, or credential handling;
- `agentq` GitHub and SSH authority;
- host/container routing and path translation;
- secret scanning and public/private configuration boundaries;
- installer behavior that can modify host state.

A Distrobox development environment is a convenience and isolation mechanism for toolchains. It is **not** a hostile-code security boundary. The unattended model sandbox used by `agentbox` has a different design and must preserve its documented isolation and import invariants.

## Reporting a vulnerability

A dedicated private vulnerability-reporting channel is not yet documented for this repository. That is a publication-readiness gap and must be resolved before the repository is made public.

Until then, do **not** put credentials, private keys, tokens, exploit payloads containing secrets, or other sensitive material in a public issue or pull request. If you already have a private communication channel with the maintainer, use it for sensitive reports.

When a private GitHub security-reporting mechanism is configured, this document should be updated to name that mechanism explicitly.

## What to include

A useful report contains:

- the affected component and version/commit;
- the security property that is violated;
- a minimal reproduction when safe to share;
- the expected and observed behavior;
- whether credential exposure, repository mutation, sandbox escape, or privilege expansion is possible;
- any evidence needed to reproduce the problem without including live secrets.

## Credential handling

Do not commit or paste live credentials into this repository. In particular, do not publish:

- SSH private keys;
- GitHub tokens or authentication files;
- Claude, Anthropic, OpenAI, or other model-provider credentials;
- session cookies or browser authentication state;
- machine-local secret overrides.

If a credential is exposed, revoke or rotate it. Removing it from the latest commit does not remove it from Git history or already-published logs.

## Security invariants

Changes must not weaken these properties without an explicit security review and evidence:

- model sandboxes do not receive GitHub push/merge authority or SSH private-key access;
- the real repository is not mounted into the unattended model sandbox;
- `agentbox` imports only validated commit ranges from disposable work;
- `agentq` applies repository policy, CI/review gates, and merge checks in the trusted layer;
- secret scanning occurs before publishing an unattended branch when policy requires it;
- portability work does not treat a different container runtime as equivalent without proving the required properties.

## Supported versions

The repository is currently a fast-moving personal toolkit and does not publish long-term supported release branches. Security fixes target the current maintained branch unless a release policy states otherwise.
