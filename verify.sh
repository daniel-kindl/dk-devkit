#!/usr/bin/env bash
#
# verify.sh - check that this machine matches the workstation definition.
#
#   ./verify.sh                 everything, with the fast devbox suite
#   ./verify.sh --full          also launch the real agent CLIs (slower)
#   ./verify.sh --no-devbox     skip the devbox routing suite
#   ./verify.sh --only 3        run one numbered module group
#   ./verify.sh --list          list the modules
#
# It runs from EITHER side: on the Bazzite host, or inside the web-dev
# container. Host-side and box-side checks are dispatched accordingly.
#
# Nothing is modified, with one documented exception: module 9 runs the
# pre-existing devbox suite, which writes inside its own scratch directory
# under ~/projects and removes it again.

REPO_ROOT=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")" && pwd)
export REPO_ROOT

RUN_DEVBOX=1
DEVBOX_FULL=0
ONLY=''

while [ $# -gt 0 ]; do
    case $1 in
        --full)      DEVBOX_FULL=1; shift ;;
        --no-devbox) RUN_DEVBOX=0; shift ;;
        --only)      ONLY=${2:?--only needs a module number}; shift 2 ;;
        --list)
            printf 'verification modules:\n'
            for m in "$REPO_ROOT"/verify/[0-9]*.sh; do
                printf '  %s\n' "$(basename "$m")"
            done
            exit 0 ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) printf 'verify.sh: unknown option: %s\n' "$1" >&2; exit 2 ;;
    esac
done
export RUN_DEVBOX DEVBOX_FULL

# shellcheck source=verify/lib.sh
. "$REPO_ROOT/verify/lib.sh"

printf '%s== workstation verification ==%s\n' "$BOLD" "$RESET"
printf 'checkout    %s\n' "$REPO_ROOT"
printf 'running on  %s\n' \
    "$( [ "$IN_CONTAINER" = 1 ] && printf 'inside the %s container' "$BOX_NAME" || printf 'the Bazzite host' )"
printf 'host home   %s\n' "$HOST_HOME"
printf 'box home    %s\n' "$BOX_HOME"

for module in "$REPO_ROOT"/verify/[0-9]*.sh; do
    base=$(basename "$module")
    if [ -n "$ONLY" ] && [ "${base%%-*}" != "${ONLY}0" ] && [ "${base%%-*}" != "$ONLY" ]; then
        continue
    fi
    # shellcheck source=/dev/null
    . "$module"
done

summary
