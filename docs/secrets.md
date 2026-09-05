# Secret policy

## The rule

No credential enters this repository. Not in a tracked file, not in a staged
file, and not in the Git history.

If it is unclear whether something is a credential, treat it as one. Fail
closed.

## What must never be tracked

| Kind | Examples on this machine |
| --- | --- |
| SSH private keys | `~/.ssh/id_ed25519` |
| GitHub authentication | `~/.config/gh/hosts.yml`, the token in the system keyring |
| Claude Code authentication | `~/.claude/.credentials.json`, `~/.claude.json` |
| Codex authentication | `~/.codex/auth.json` |
| Agent session state | `~/.claude/sessions/`, `~/.codex/*.sqlite`, `history.jsonl` |
| Keyrings and password stores | `~/.gnupg/`, `~/.pki/`, KWallet |
| Caches, logs, histories | `~/.cache/`, `~/.bash_history` |
| Machine identifiers | `installation_id`, `device-id` |
| Unattended agent credentials | `~/.config/agentbox/secrets.env` |

The `.gitignore` denies all of these by pattern. `verify.sh` module 7 proves it:
it asks `git check-ignore` about a list of real credential paths, and fails if
any one of them would be accepted.

## The SSH key

The private key stays on the host, and only on the host.

- Do not copy it into a container.
- Do not copy it into this repository.
- Do not store a passphrase anywhere.
- Do not rewrite a repository SSH origin to HTTPS.

The container reaches GitHub through the **host ssh-agent**, not through a copy
of the key. Distrobox mounts `/run/user/1000` into the container, so
`$SSH_AUTH_SOCK` already points at the host agent socket inside `web-dev`.
`verify.sh` checks that the socket is visible and that the agent holds at least
one key. It prints the count, never a fingerprint and never key material.

To restore the key on a new machine, use your own backup, for example the
Bitwarden vault that this workstation already installs. Then:

```bash
install -m 700 -d ~/.ssh
install -m 600 /path/to/id_ed25519     ~/.ssh/id_ed25519
install -m 644 /path/to/id_ed25519.pub ~/.ssh/id_ed25519.pub
ssh-add ~/.ssh/id_ed25519
ssh -T git@github.com                   # expect: "Hi <user>! You've successfully authenticated"
```

## Credentials for unattended agents

`bin/agentbox` runs an agent with no human present. It needs a model credential,
and the rule above still holds: the credential never enters this repository.

It lives in `~/.config/agentbox/secrets.env`, mode 600.
`bootstrap/host.sh` creates that file as a commented template and never writes a
value into it.

| Agent | Variable | How to get it |
| --- | --- | --- |
| Claude | `CLAUDE_CODE_OAUTH_TOKEN` | `claude setup-token` on the host |
| Claude | `ANTHROPIC_API_KEY` | an API key, as an alternative |
| Codex | `OPENAI_API_KEY` | an API key |

Use a **dedicated** token for unattended runs. `claude setup-token` mints one
that can be revoked on its own. Do not copy the token out of an interactive
session: revoking that one also ends your own sessions.

Two files are deliberately **not** delegated to a sandbox:

- `~/.claude/.credentials.json` is the interactive session credential.
- `~/.codex/auth.json` is a full ChatGPT sign-in.

Mounting either into a container that runs unattended model output would hand
over far more than a single run needs. When `OPENAI_API_KEY` is absent,
`agentbox` skips the review step and says so, rather than reaching for
`auth.json`.

That file is the only source. `agentbox` does **not** take
`ANTHROPIC_API_KEY` or any other credential from the shell that starts it: an
interactive shell often exports one for its own use, and delegating it to an
unattended sandbox silently is not a choice the user made. Pass
`--use-ambient-credentials` to ask for that on purpose.

A sandbox also never receives the private SSH key or the ssh-agent socket, so it
cannot push, open a pull request, or merge on GitHub. `agentbox selftest` proves
this from inside a running sandbox, and the same probes run on every real run.

### How the credential reaches a sandbox

`agentbox` copies the values it needs into
`~/.local/share/agentbox/runs/<run-id>/creds/agent.env`, mode 600, and mounts
that file read-only into the sandbox. The sandbox image puts a shim in front of
`claude` and `codex` on `PATH`; the shim reads the file — it never sources it,
because a sourced file is code — and exports the value inside the CLI's own
process.

A credential value is therefore never a `podman` argument, never in the control
plane's environment, and never in `/proc/<pid>/cmdline`. The file is removed as
soon as the run ends, even when the run directory is kept for inspection.

Two limits belong here rather than only in `docs/sandcastle.md`:

- Run output passes through a filter that replaces the exact configured
  credential values before it reaches your terminal or a log. This is defense
  in depth only. The sandbox has a network connection and holds the
  credential, so an agent that wants to send it somewhere can.
- The control plane can read the credential file, because Sandcastle validates
  every sandbox mount source from inside the runner. It never puts the value
  in an argument or in its own environment.

## Scanning

```bash
bin/scan-secrets              # tracked and staged files (the default)
bin/scan-secrets --history    # every blob in the whole Git history
bin/scan-secrets --all        # every file in the working tree
```

The scanner reports the file and the rule that matched. It never prints the
matched text, so a finding is safe to paste into an issue. Exit code 1 means
findings; exit code 0 means clean.

Run it before every commit. `verify.sh` runs both the tracked scan and the
history scan.

The scanner writes its own rules with split string literals, for example
`gh` + `p_`, so that the rule file never matches its own patterns.

## What authentication remains manual

A restore cannot reproduce authentication, and it should not try. After a
bootstrap, these steps are yours:

1. Restore and load the SSH key (above).
2. `gh auth login --git-protocol ssh`, on the host and inside `web-dev`.
3. `claude`, then `/login`.
4. `codex login`.

`docs/recovery.md` lists these in order, with the rest of the sequence.
