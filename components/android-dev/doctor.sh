#!/usr/bin/env bash
# Check the installed Android Emulator controls command.
set -euo pipefail

REPO_ROOT=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/../.." && pwd)
COMMAND=$HOME/.local/bin/android-emulator-controls

[ -x "$COMMAND" ] || {
    printf 'android-emulator-controls is not installed in ~/.local/bin\n' >&2
    exit 1
}
[ "$COMMAND" -ef "$REPO_ROOT/bin/android-emulator-controls" ] || {
    printf 'the installed android-emulator-controls is not this checkout\n' >&2
    exit 1
}
exec "$COMMAND" --check
