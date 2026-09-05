#!/usr/bin/env bash
#
# Report whether the agentq host entry point is ready.
set -euo pipefail

[ -x "$HOME/.local/bin/agentq" ] ||
    { echo 'the agentq host shim is not installed' >&2; exit 1; }
exec "$HOME/.local/bin/agentq" doctor
