#!/usr/bin/env bash
#
# Install the host CLI tools in manifests/homebrew.txt.
#
#   components/host-cli-tools/install.sh [--dry-run]
#
# It installs no Node, npm, Python or uv toolchain on the host.

REPO_ROOT=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/../.." && pwd)
# shellcheck source=../../bootstrap/lib/common.sh
. "$REPO_ROOT/bootstrap/lib/common.sh"
# shellcheck source=../../bootstrap/lib/component.sh
. "$REPO_ROOT/bootstrap/lib/component.sh"
# shellcheck source=../../bootstrap/lib/host-packages.sh
. "$REPO_ROOT/bootstrap/lib/host-packages.sh"

component_args "$@"

section 'Homebrew (host CLI tools)'
install_homebrew_packages "$REPO_ROOT"
summary
