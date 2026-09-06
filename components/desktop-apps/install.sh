#!/usr/bin/env bash
#
# Install the desktop applications in manifests/flatpaks.txt.
#
#   components/desktop-apps/install.sh [--dry-run]

REPO_ROOT=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/../.." && pwd)
# shellcheck source=../../bootstrap/lib/common.sh
. "$REPO_ROOT/bootstrap/lib/common.sh"
# shellcheck source=../../bootstrap/lib/component.sh
. "$REPO_ROOT/bootstrap/lib/component.sh"
# shellcheck source=../../bootstrap/lib/platform.sh
. "$REPO_ROOT/bootstrap/lib/platform.sh"
# shellcheck source=../../bootstrap/lib/host-packages.sh
. "$REPO_ROOT/bootstrap/lib/host-packages.sh"

component_args "$@"

section 'Flatpak applications'
install_flatpak_apps "$REPO_ROOT"
summary
