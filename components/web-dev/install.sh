#!/usr/bin/env bash
#
# Create the web-dev environment and converge its toolchain.
#
#   components/web-dev/install.sh [--dry-run]
#
# The container is created from distrobox/web-dev.ini when it is absent, and an
# existing container is never touched. The toolchain converges inside the
# container, through the router, because the host keeps no Node toolchain.

REPO_ROOT=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/../.." && pwd)
# shellcheck source=../../bootstrap/lib/common.sh
. "$REPO_ROOT/bootstrap/lib/common.sh"
# shellcheck source=../../bootstrap/lib/component.sh
. "$REPO_ROOT/bootstrap/lib/component.sh"
# shellcheck source=../../bootstrap/lib/environments.sh
. "$REPO_ROOT/bootstrap/lib/environments.sh"

component_args "$@"

section 'web-dev container'
create_development_environment "$REPO_ROOT" web-dev

section 'web-dev toolchain'
box_bootstrap=(./bootstrap/web-dev.sh)
[ "$DRY_RUN" = 1 ] && box_bootstrap+=(--dry-run)
run "$REPO_ROOT/bin/devbox" exec web-dev --cwd "$REPO_ROOT" -- "${box_bootstrap[@]}"

summary
