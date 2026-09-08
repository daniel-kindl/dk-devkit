#!/usr/bin/env bash
#
# Report whether the repository label tool is ready.
#
# Readiness is a fact about the INSTALLED command, not about the file in this
# checkout: a reader is told to type "repo-labels", so that is what must exist,
# resolve to this checkout, and answer.
set -euo pipefail
REPO_ROOT=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/../.." && pwd)
COMMAND=$HOME/.local/bin/repo-labels

[ -x "$REPO_ROOT/bin/repo-labels" ] ||
    { echo 'bin/repo-labels is not executable' >&2; exit 1; }
[ -x "$COMMAND" ] ||
    { echo 'the repo-labels command is not installed in ~/.local/bin' >&2; exit 1; }
[ "$COMMAND" -ef "$REPO_ROOT/bin/repo-labels" ] ||
    { echo 'the installed repo-labels command is not this checkout' >&2; exit 1; }
exec "$COMMAND" --help
