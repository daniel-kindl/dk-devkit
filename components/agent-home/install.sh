#!/usr/bin/env bash
#
# Install the shared agent policy, status line and client preferences into the
# host agent home.
#
#   components/agent-home/install.sh [--dry-run]
#
# It merges absent keys only. It never changes a value a client wrote, and it
# never writes a credential.

REPO_ROOT=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/../.." && pwd)
# shellcheck source=../../bootstrap/lib/common.sh
. "$REPO_ROOT/bootstrap/lib/common.sh"
# shellcheck source=../../bootstrap/lib/component.sh
. "$REPO_ROOT/bootstrap/lib/component.sh"
# shellcheck source=../../bootstrap/lib/agent-home.sh
. "$REPO_ROOT/bootstrap/lib/agent-home.sh"

component_args "$@"
install_host_agent_home "$REPO_ROOT"
summary
