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
# shellcheck source=../../bootstrap/lib/environments.sh
. "$REPO_ROOT/bootstrap/lib/environments.sh"

component_args "$@"

section 'Windows virtual machine (winbox)'
install_user_command "$REPO_ROOT" winbox

# The same command name inside every development environment. An agent runs
# in the environment that owns a repository, and each one has an isolated
# HOME, so the host link cannot be seen from any of them.
#
# This installs a NAME, not a machine. There is ONE virtual machine on this
# computer: the container name is fixed in the manifest, and winbox resolves
# its disk, its key and its account from the HOST home whichever side it runs
# on. An agent in python-dev and an agent in web-dev reach the same Windows.
section 'The same command inside the development environments'
install_environment_command "$REPO_ROOT" winbox

manual 'Create the machine once, on the host: winbox up --wait'
summary
