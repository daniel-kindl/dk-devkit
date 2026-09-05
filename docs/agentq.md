# agentq

`agentq` is the trusted GitHub backlog coordinator for unattended repository work.

It is intentionally separate from `agentbox`:

```text
agentq (trusted)
  reads GitHub issues
  claims work
  starts agentbox
  pushes validated branches
  opens PRs
  waits for CI/review gates
  merges only when policy permits

agentbox (untrusted execution boundary)
  creates a disposable clone
  runs the model in an isolated sandbox
  runs deterministic checks
  validates the imported commit range
  never receives GitHub push/merge authority
```

## CLI

Run from the repository you want to process:

```bash
agentq run
```

The supported commands are:

```text
agentq run      process eligible issues until no runnable work remains
agentq plan     show what a run would do without mutation
agentq doctor   report repository and machine readiness
agentq policy   show the resolved policy and its sources
agentq init     write a starter repository policy
```

`--repo PATH` is an explicit override. Without it, `agentq` resolves the Git working tree that contains the current directory.

The obsolete `agentqueue` executable is not an alias and is not supported after convergence.

## Output

The default terminal view is the compact stage view. `--verbose`, `--debug`, `--quiet`, and `--json` change presentation only; the run log keeps the coordinator evidence.

Typical stages are:

```text
CLAIM -> IMPLEMENT -> CHECK -> REVIEW -> IMPORT -> PUSH -> PR -> CI -> MERGE -> DONE
```

## Policy

Repository policy remains in `.agentqueue.json` during the CLI rename. The file name is a durable policy-format identifier, not the product name. Existing enrolled repositories therefore do not need a policy migration merely because the executable became `agentq`.

The built-in policy defaults also remain under `config/agentqueue/` for the same reason in this change.

## Durable compatibility identifiers

The clean break applies to the **supported command and human-facing product name**. The following internal/durable identifiers remain intentionally stable in this change:

- `.agentqueue.json` repository policy files;
- `AGENTQUEUE_*` internal environment/configuration variables;
- `~/.local/share/agentqueue` existing run evidence;
- `~/.config/agentqueue` existing machine-local policy state;
- the internal Python package name `agentqueue`;
- historical machine-readable GitHub markers such as `<!-- agentqueue:claim v1 -->`.

Keeping those identifiers stable prevents a cosmetic CLI rename from breaking stale-claim recovery, existing repository enrollment, run evidence, or machine-local configuration. New human-readable messages and commands use `agentq`.

## Host/container routing

The real coordinator runtime is installed inside `web-dev`, where `gh` and the forwarded SSH agent are available. The host receives a generated `agentq` devbox-router shim. The shim maps the current working directory and path-valued options across the host/container boundary, then delegates to the container-side command.

`bootstrap/host.sh` refreshes the `agentq` host shim and removes an obsolete installed `agentqueue` entry point. `bootstrap/web-dev.sh` installs the real `agentq` command.

## Authority boundary

`agentq` is trusted. It can use GitHub authentication and the forwarded SSH agent. Model sandboxes cannot.

A model result is not pushed directly. `agentbox` first validates the disposable-clone result and imports only an accepted commit range. `agentq` then applies repository policy, CI, review, and merge gates in the trusted layer.

## Recovery

A coordinator interruption must leave durable claim/release evidence and recoverable repository state. Historical claim protocol markers intentionally keep their `agentqueue:*` schema name so existing records remain readable.

Use `agentq doctor` before retrying work after an environment/bootstrap change. See `docs/recovery.md` for broader workstation recovery procedures.
