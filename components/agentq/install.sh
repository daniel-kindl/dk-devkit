#!/usr/bin/env bash
#
# Install the agentq host entry point.
#
#   components/agentq/install.sh [--dry-run]
#
# The host gets the command as a router shim. The coordinator runtime stays in
# the environment that manifests/agentqueue.env names, because it needs gh and
# the forwarded ssh-agent. The shim holds no runtime, state or credential.

REPO_ROOT=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/../.." && pwd)
# shellcheck source=../../bootstrap/lib/common.sh
. "$REPO_ROOT/bootstrap/lib/common.sh"
# shellcheck source=../../bootstrap/lib/component.sh
. "$REPO_ROOT/bootstrap/lib/component.sh"
# shellcheck source=../../bootstrap/lib/agentq.sh
. "$REPO_ROOT/bootstrap/lib/agentq.sh"

component_args "$@"

section 'GitHub backlog coordinator host entry point (agentq)'
install_agentq_host_shim "$REPO_ROOT"
summary
