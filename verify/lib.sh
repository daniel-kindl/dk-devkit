# Shared helpers for the workstation verification modules.
# Source this file; do not execute it.
#
# Verification never modifies the system. The only exception is the existing
# devbox suite in verify/90-devbox.sh, which writes inside its own scratch
# directory and cleans up after itself.

PASSED=0
FAILED=0
SKIPPED=0
declare -a FAILURES=()

BOLD=''; DIM=''; RED=''; GREEN=''; YELLOW=''; RESET=''
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'
    GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'
fi

section() { printf '\n%s%s%s\n' "$BOLD" "$1" "$RESET"; }

pass() { printf '  %sPASS%s  %s\n' "$GREEN" "$RESET" "$1"; PASSED=$(( PASSED + 1 )); }
skip() { printf '  %sSKIP%s  %s  %s(%s)%s\n' "$YELLOW" "$RESET" "$1" "$DIM" "$2" "$RESET"; SKIPPED=$(( SKIPPED + 1 )); }
fail() {
    local name=$1; shift
    printf '  %sFAIL%s  %s\n' "$RED" "$RESET" "$name"
    local line
    for line in "$@"; do printf '        %s\n' "$line"; done
    FAILED=$(( FAILED + 1 ))
    FAILURES+=("$name")
}

# --------------------------------------------------------------- assertions --

# check <name> -- <command...>   passes when the command exits 0
check() {
    local name=$1; shift
    [ "${1:-}" = -- ] && shift
    local out rc=0
    out=$("$@" 2>&1) || rc=$?
    if [ "$rc" -eq 0 ]; then
        pass "$name"
    else
        fail "$name" "exit $rc" "${out:-(no output)}"
    fi
}

# check_eq <name> <expected> <actual>
check_eq() {
    local name=$1 want=$2 got=$3
    if [ "$want" = "$got" ]; then
        pass "$name"
    else
        fail "$name" "expected: [$want]" "actual:   [$got]"
    fi
}

# check_contains <name> <needle> <haystack>
check_contains() {
    local name=$1 needle=$2 hay=$3
    case $hay in
        *"$needle"*) pass "$name" ;;
        *) fail "$name" "expected to contain: [$needle]" "actual: ${hay//$'\n'/ | }" ;;
    esac
}

# check_not_contains <name> <needle> <haystack>
check_not_contains() {
    local name=$1 needle=$2 hay=$3
    case $hay in
        *"$needle"*) fail "$name" "expected NOT to contain: [$needle]" \
                          "actual: ${hay//$'\n'/ | }" ;;
        *) pass "$name" ;;
    esac
}

# check_link <name> <link> <expected target>
#
# The comparison uses "-ef" (same device and inode), not string equality: the
# same file has several valid spellings here (/home vs /var/home, /workspace vs
# ~/projects, /run/host/... from inside the container), and all of them are
# correct.
check_link() {
    local name=$1 link=$2 want=$3
    if [ ! -L "$link" ]; then
        if [ -e "$link" ]; then
            fail "$name" "$link exists but is not a symlink"
        else
            fail "$name" "$link does not exist"
        fi
        return
    fi
    if [ ! -e "$link" ]; then
        fail "$name" "$link is a dangling symlink -> $(readlink -- "$link" 2>/dev/null)"
        return
    fi
    if [ "$link" -ef "$want" ]; then
        pass "$name"
    else
        fail "$name" "expected it to resolve to: $want" \
                     "actual target:              $(readlink -f -- "$link" 2>/dev/null)"
    fi
}

# ----------------------------------------------------------------- contexts --

IN_CONTAINER=0
if [ -f /run/.containerenv ] || [ -f /.dockerenv ]; then IN_CONTAINER=1; fi
export IN_CONTAINER

BOX_NAME=${WORKSTATION_BOX:-web-dev}

# distrobox-host-exec carries the container working directory over to the host.
# When that directory does not exist on the host, and /workspace does not, the
# host side exits 127 before it runs anything. Every host call therefore starts
# from a directory that exists on both sides.
HOST_SAFE_CWD=/

# on_host <command...> - run a command on the Bazzite host from either side.
on_host() {
    if [ "$IN_CONTAINER" = 1 ]; then
        ( cd "$HOST_SAFE_CWD" && distrobox-host-exec "$@" )
    else
        "$@"
    fi
}

# host_sh <shell-snippet> - run a snippet in a host login shell.
host_sh() {
    if [ "$IN_CONTAINER" = 1 ]; then
        ( cd "$HOST_SAFE_CWD" && distrobox-host-exec bash -lc "$1" )
    else
        bash -lc "$1"
    fi
}

# box_sh <shell-snippet> - run a snippet in the web-dev login shell.
box_sh() {
    if [ "$IN_CONTAINER" = 1 ]; then
        bash -lc "$1"
    else
        distrobox enter -T --name "$BOX_NAME" -- bash -lc "$1" 2>/dev/null
    fi
}

# HOST_HOME is the host home directory, spelled as the host spells it.
if [ "$IN_CONTAINER" = 1 ]; then
    HOST_HOME=${DISTROBOX_HOST_HOME:-/home/$USER}
    HOST_HOME_VIEW=/run/host$(readlink -f "$HOST_HOME" 2>/dev/null || printf '%s' "$HOST_HOME")
else
    HOST_HOME=$HOME
    HOST_HOME_VIEW=$HOME
fi
export HOST_HOME HOST_HOME_VIEW

# BOX_HOME is the isolated HOME of the web-dev container.
BOX_HOME=${WORKSTATION_BOX_HOME:-$HOST_HOME/.local/share/distrobox-homes/$BOX_NAME}
export BOX_HOME

summary() {
    printf '\n%s== summary ==%s\n' "$BOLD" "$RESET"
    printf 'passed   %d\nfailed   %d\nskipped  %d\n' "$PASSED" "$FAILED" "$SKIPPED"
    if [ "$FAILED" -gt 0 ]; then
        printf '\n%sfailed checks:%s\n' "$RED" "$RESET"
        local f
        for f in "${FAILURES[@]}"; do printf '  - %s\n' "$f"; done
        return 1
    fi
    return 0
}
