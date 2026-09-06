#!/usr/bin/env bash
#
# Install the devbox router component.
#
#   components/devbox/install.sh [--dry-run]
#
# It installs the router, the agent host shims and the router configuration.
# It creates no container, installs no toolchain and writes no credential.

REPO_ROOT=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/../.." && pwd)
# shellcheck source=../../bootstrap/lib/common.sh
. "$REPO_ROOT/bootstrap/lib/common.sh"
# shellcheck source=../../bootstrap/lib/component.sh
. "$REPO_ROOT/bootstrap/lib/component.sh"
# shellcheck source=../../bootstrap/lib/environments.sh
. "$REPO_ROOT/bootstrap/lib/environments.sh"
# shellcheck source=../../bootstrap/lib/devbox.sh
. "$REPO_ROOT/bootstrap/lib/devbox.sh"

component_args "$@"
install_devbox_router "$REPO_ROOT"
summary
