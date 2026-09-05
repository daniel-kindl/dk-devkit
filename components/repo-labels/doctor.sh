#!/usr/bin/env bash
#
# Report whether the repository label tool is ready.
set -euo pipefail
REPO_ROOT=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/../.." && pwd)

[ -x "$REPO_ROOT/bin/repo-labels" ] ||
    { echo 'bin/repo-labels is not executable' >&2; exit 1; }
exec python3 "$REPO_ROOT/bin/repo-labels" --help
