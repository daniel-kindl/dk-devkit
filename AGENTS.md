# Agent instructions for the workstation repository

This repository defines a Bazzite development workstation. It is infrastructure
configuration, not an application.

The global policy in `config/agents/AGENTS.md` also applies here. That file is
the canonical shared agent policy, and `~/.agents/AGENTS.md` is a symlink to it.
Edit it only through this repository.

## Rules for changes in this repository

1. **Never commit a credential.** Run `bin/scan-secrets` before every commit.
   The scan must report zero findings. If the result is unclear, stop and ask.
   `docs/secrets.md` lists what stays out and why.

2. **Separate declarative state from runtime state.** Track scripts, manifests,
   templates, policies, environment definitions and verification logic. Do not
   track tokens, session state, caches, histories, logs, installed toolchains,
   or absolute paths that only exist on one machine.

3. **Keep every installer idempotent.** Check the current state first, then
   change only what does not match. Prefer this to a destructive replacement.
   Preserve configuration that this repository does not own.

4. **Respect the host/container boundary.**
   - The Bazzite host gets Homebrew CLI tools, Flatpak applications, Orca, the
     `devbox` router and the agent shims.
   - A Distrobox container gets the language toolchain and the agent CLIs.
   - Never add a Node or npm toolchain to the host.
   - Never copy a private SSH key into a container or into this repository.

5. **Do not weaken an existing boundary.** The isolated container HOME, the
   forwarded ssh-agent socket, the read-only host key material and the router
   recursion guard are all deliberate.

6. **Verify before you claim.** `./verify.sh` must pass. When you change the
   router, `bin/devbox-verify` must also pass.

7. **Keep the unattended agent boundary closed.** `bin/agentbox` runs model
   output with no human watching. The boundary is a **disposable clone**: an
   unattended sandbox never receives the real repository, its `.git`, the
   canonical `~/.agents`, or the canonical skill store. Only commits that pass
   host-side validation enter the real repository, and only on an `agent/`
   branch. Never bind-mount a canonical path into a sandbox, never pass a
   credential value as an argument, never run a command the disposable clone
   configures, and never weaken the import validation. `verify.sh` module 8
   checks each of these, `agentbox selftest --adversarial` proves them on a
   live machine, and `docs/sandcastle.md` says why.

8. **Keep the GitHub authority on the trusted side.** `bin/agentqueue` holds
   the `gh` sign-in, the ssh-agent and the right to push, open a pull request
   and merge. `bin/agentbox` holds none of them, and a sandbox holds nothing
   that authenticates to GitHub. Never give a sandbox a GitHub credential,
   never read a token into `lib/agentqueue`, and never let the coordinator
   write outside the `agent/` namespace. `verify.sh` module 8b checks each of
   these, and `docs/agentqueue.md` says why.

   The host `agentqueue` command is a router shim and must stay one. It holds
   no runtime, no state and no credential, and it delegates to the environment
   that `manifests/agentqueue.env` names. `verify.sh` module 8c checks that.

9. **Do not special-case a repository.** The router already resolves an
   environment from `.devbox`, from the git-common-dir, from `repos.tsv`, and
   from the inference rules. The queue policy resolves the same way, from
   `<repo>/.agentqueue.json` and the built-in default. Add a generic rule, not
   an exception.

## Prose

Use ASD-STE100 as the baseline, in STE-flavored mode, for the documentation,
the code comments, the commit messages and the pull request descriptions. Keep
one term for one concept. Keep sentences short. Do not add a fact that the
source does not contain.
