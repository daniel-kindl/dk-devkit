#!/usr/bin/env bash
#
# Install Pi on the host.
#
#   components/pi/install.sh [--dry-run]
#
# There is exactly one Pi installation and it lives on the host. This installs
# no Pi into a development environment, creates no container, and adds no Node
# development toolchain to the host: Pi gets its own private runtime instead.

REPO_ROOT=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/../.." && pwd)
# shellcheck source=../../bootstrap/lib/common.sh
. "$REPO_ROOT/bootstrap/lib/common.sh"
# shellcheck source=../../bootstrap/lib/component.sh
. "$REPO_ROOT/bootstrap/lib/component.sh"
# shellcheck source=../../bootstrap/lib/pi.sh
. "$REPO_ROOT/bootstrap/lib/pi.sh"

component_args "$@"
install_host_pi "$REPO_ROOT"
summary
