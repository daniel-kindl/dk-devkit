#!/usr/bin/env bash
#
# Create golang-dev and converge its Go toolchain.
#
#   components/golang-dev/install.sh [--dry-run]

REPO_ROOT=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/../.." && pwd)
# shellcheck source=../../bootstrap/lib/common.sh
. "$REPO_ROOT/bootstrap/lib/common.sh"
# shellcheck source=../../bootstrap/lib/component.sh
. "$REPO_ROOT/bootstrap/lib/component.sh"
# shellcheck source=../../bootstrap/lib/environments.sh
. "$REPO_ROOT/bootstrap/lib/environments.sh"

component_args "$@"

section 'golang-dev container'
create_development_environment "$REPO_ROOT" golang-dev

section 'golang-dev toolchain'
box_bootstrap=(./bootstrap/golang-dev.sh)
[ "$DRY_RUN" = 1 ] && box_bootstrap+=(--dry-run)
run "$REPO_ROOT/bin/devbox" exec golang-dev --cwd "$REPO_ROOT" -- "${box_bootstrap[@]}"

summary
