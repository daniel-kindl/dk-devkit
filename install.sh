#!/usr/bin/env bash
#
# install.sh - install reusable toolkit components on this machine.
#
#   ./install.sh                              pick the components on a terminal
#   ./install.sh --list                       show every component
#   ./install.sh --dry-run --components X     show the resolved plan only
#   ./install.sh --components devbox,web-dev  install those, and what they need
#   ./install.sh --profile developer          a tracked component set
#   ./install.sh --profile daniel             the complete personal workstation
#
# The installer selects nothing on its own. It resolves the dependency and
# capability closure of what you name, shows the plan, converges the components
# in deterministic order, and verifies only the components it selected.
#
# With no selection it opens the picker, but only on a terminal. A run that
# cannot answer a question gets a usage error instead of a prompt.
#
# It collects no credential. A component that needs authentication reports it
# as a manual step instead.
#
# bootstrap/host.sh stays supported. Both entry points call the same library
# functions.
set -euo pipefail

REPO_ROOT=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")" && pwd)

if ! command -v python3 >/dev/null 2>&1; then
    printf 'install.sh: python3 is required to resolve the component graph\n' >&2
    exit 2
fi

exec python3 "$REPO_ROOT/bin/toolkit-install" "$@"
