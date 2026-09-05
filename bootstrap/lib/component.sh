# Shared preamble for a toolkit component operation script.
# Source this file after bootstrap/lib/common.sh; do not execute it.
#
# Every component operation is a plain script that the root installer runs. It
# accepts the one option the installer passes, so a component can also be run
# by hand exactly as the installer runs it.

# component_args [--dry-run]
component_args() {
    while [ $# -gt 0 ]; do
        case $1 in
            --dry-run) DRY_RUN=1; shift ;;
            -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
            *) die "unknown option: $1" ;;
        esac
    done
}

# component_root - the checkout that holds this component.
component_root() {
    cd -- "$(dirname -- "$(readlink -f -- "$1")")/../.." && pwd
}
