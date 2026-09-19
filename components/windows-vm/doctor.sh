#!/usr/bin/env bash
#
# Report whether the windows-vm component is ready.
#
# Readiness is a fact about the INSTALLED command, not about the file in this
# checkout: a reader is told to type "winbox", so that is what must exist,
# resolve to this checkout, and answer.
#
# The runtime doctor in bin/winbox then answers for the machine: the two
# devices, the container engine, the image and the state of the machine itself.
# It does not create anything.
set -euo pipefail
REPO_ROOT=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/../.." && pwd)
COMMAND=$HOME/.local/bin/winbox

[ -x "$REPO_ROOT/bin/winbox" ] ||
    { echo 'bin/winbox is not executable' >&2; exit 1; }
[ -x "$COMMAND" ] ||
    { echo 'the winbox command is not installed in ~/.local/bin' >&2; exit 1; }
[ "$COMMAND" -ef "$REPO_ROOT/bin/winbox" ] ||
    { echo 'the installed winbox command is not this checkout' >&2; exit 1; }
exec "$COMMAND" doctor
