#!/usr/bin/env bash
#
# Install the winbox command.
#
#   components/windows-vm/install.sh [--dry-run]
#
# It installs the command only. It pulls no image and creates no machine: the
# first start downloads several gigabytes and installs Windows, which takes
# tens of minutes, so it stays an explicit "winbox up".
#
# It writes no credential either. The Windows password is made by the first
# "winbox up", in a file with mode 0600 outside this checkout.

REPO_ROOT=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/../.." && pwd)
# shellcheck source=../../bootstrap/lib/common.sh
. "$REPO_ROOT/bootstrap/lib/common.sh"
# shellcheck source=../../bootstrap/lib/component.sh
. "$REPO_ROOT/bootstrap/lib/component.sh"

component_args "$@"

section 'Windows virtual machine (winbox)'
install_user_command "$REPO_ROOT" winbox
manual 'Create the machine once: winbox up --wait'
summary
