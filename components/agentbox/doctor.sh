#!/usr/bin/env bash
#
# Report whether the agentbox component is ready.
#
# The runtime doctor in bin/agentbox answers for the machine: git, python3,
# timeout, the Podman client and the images. It cannot answer for the
# component, because it runs whatever path invoked it. This wrapper proves the
# public entry point first, so a deleted ~/.local/bin/agentbox is repaired by
# the next run instead of being hidden by a healthy runtime.
#
# git and python3 are declared capabilities of this component. "timeout" is not:
# it is part of the coreutils of every platform the adapters describe, and the
# runtime doctor reports it where a run would need it.
set -euo pipefail
REPO_ROOT=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/../.." && pwd)
COMMAND=$HOME/.local/bin/agentbox

[ -x "$COMMAND" ] ||
    { echo 'the agentbox command is not installed in ~/.local/bin' >&2; exit 1; }
[ "$COMMAND" -ef "$REPO_ROOT/bin/agentbox" ] ||
    { echo 'the installed agentbox command is not this checkout' >&2; exit 1; }
exec "$COMMAND" doctor
