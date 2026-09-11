#!/usr/bin/env bash
#
# Install the agentbox CLIs and prepare the credential file location.
#
#   components/agentbox/install.sh [--dry-run]
#
# It never writes a credential value, and it never builds an image: an image
# build needs the network and takes minutes, so it stays an explicit command.

REPO_ROOT=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/../.." && pwd)
# shellcheck source=../../bootstrap/lib/common.sh
. "$REPO_ROOT/bootstrap/lib/common.sh"
# shellcheck source=../../bootstrap/lib/component.sh
. "$REPO_ROOT/bootstrap/lib/component.sh"
# shellcheck source=../../bootstrap/lib/sandcastle.sh
. "$REPO_ROOT/bootstrap/lib/sandcastle.sh"

component_args "$@"

section 'Agent orchestration (agentbox)'
install_agentbox "$REPO_ROOT"
summary
