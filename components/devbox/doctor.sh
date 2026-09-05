#!/usr/bin/env bash
#
# Report whether the devbox router is ready.
set -euo pipefail
REPO_ROOT=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/../.." && pwd)

[ -x "$HOME/.local/bin/devbox" ] || { echo 'devbox is not installed in ~/.local/bin' >&2; exit 1; }
[ -e "$HOME/.config/devbox-router/settings.env" ] ||
    { echo 'the router configuration is not installed' >&2; exit 1; }
exec "$REPO_ROOT/bin/devbox" doctor
