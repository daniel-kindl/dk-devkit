#!/usr/bin/env bash
#
# Install the repository label tool as a user command.
#
#   components/repo-labels/install.sh [--dry-run]
#
# It installs the command only. It reads no repository, contacts no network
# and writes no credential: the GitHub login stays a manual step.

REPO_ROOT=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/../.." && pwd)
# shellcheck source=../../bootstrap/lib/common.sh
. "$REPO_ROOT/bootstrap/lib/common.sh"
# shellcheck source=../../bootstrap/lib/component.sh
. "$REPO_ROOT/bootstrap/lib/component.sh"

component_args "$@"

section 'Repository tooling (repo-labels)'
install_user_command "$REPO_ROOT" repo-labels
summary
