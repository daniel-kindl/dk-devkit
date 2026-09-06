#!/usr/bin/env bash
#
# Report whether the repository metadata tool is ready.
set -euo pipefail
REPO_ROOT=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/../.." && pwd)

[ -x "$REPO_ROOT/bin/repo-meta" ] ||
    { echo 'bin/repo-meta is not executable' >&2; exit 1; }
exec python3 "$REPO_ROOT/bin/repo-meta" --help
