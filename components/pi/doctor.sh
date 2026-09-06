#!/usr/bin/env bash
#
# Report whether the host Pi installation is ready.
#
# It reads the machine and makes no network call, so a converged machine
# installs nothing again. It also compares the generated launcher against the
# text this checkout would write now, so a change in this repository is
# converged by the next run instead of being reported as ready.
set -euo pipefail
REPO_ROOT=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/../.." && pwd)
# shellcheck source=../../bootstrap/lib/common.sh
. "$REPO_ROOT/bootstrap/lib/common.sh"
# shellcheck source=../../bootstrap/lib/pi.sh
. "$REPO_ROOT/bootstrap/lib/pi.sh"

pi_manifest "$REPO_ROOT"

pi_node_is_new_enough "$PI_RUNTIME_BIN/node" ||
    { echo "the private Pi runtime is absent or older than $PI_NODE_MIN_VERSION" >&2; exit 1; }
[ -e "$PI_ENTRY" ] || { echo 'the Pi package is not installed' >&2; exit 1; }
[ -x "$PI_LAUNCHER" ] || { echo 'the host pi command is not installed' >&2; exit 1; }
pi_launcher_text | cmp -s - "$PI_LAUNCHER" ||
    { echo 'the host pi command is out of date with this checkout' >&2; exit 1; }
[ -L "$PI_AGENT_DIR/AGENTS.md" ] ||
    { echo 'Pi does not read the shared agent policy yet' >&2; exit 1; }

exec "$PI_LAUNCHER" --version >/dev/null
