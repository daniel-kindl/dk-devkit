# Shared helpers for the workstation bootstrap scripts.
# Source this file; do not execute it.
#
# Every helper is idempotent: it checks the current state first and changes
# only what does not match. Anything it replaces is copied into a backup
# directory first.

set -euo pipefail

: "${DRY_RUN:=0}"
: "${BACKUP_DIR:=}"

BOLD=''; DIM=''; RED=''; GREEN=''; YELLOW=''; RESET=''
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'
    GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'
fi

CHANGED=0
SKIPPED=0
MANUAL=()

section() { printf '\n%s==> %s%s\n' "$BOLD" "$1" "$RESET"; }
ok()      { printf '  %sok%s      %s\n' "$GREEN" "$RESET" "$1"; SKIPPED=$(( SKIPPED + 1 )); }
change()  { printf '  %schange%s  %s\n' "$YELLOW" "$RESET" "$1"; CHANGED=$(( CHANGED + 1 )); }
info()    { printf '  %s%s%s\n' "$DIM" "$1" "$RESET"; }
warn()    { printf '  %swarn%s    %s\n' "$YELLOW" "$RESET" "$1" >&2; }
die()     { printf '  %serror%s   %s\n' "$RED" "$RESET" "$1" >&2; exit 1; }
manual()  { MANUAL+=("$1"); }

run() {
    if [ "$DRY_RUN" = 1 ]; then
        printf '  %swould run:%s %s\n' "$DIM" "$RESET" "$*"
        return 0
    fi
    "$@"
}

have() { command -v "$1" >/dev/null 2>&1; }

backup_dir() {
    if [ -z "$BACKUP_DIR" ]; then
        BACKUP_DIR="$HOME/.agents/backups/$(date +%Y%m%d-%H%M%S)"
    fi
    printf '%s' "$BACKUP_DIR"
}

# save_copy <path> - keep a copy of an existing path before it is replaced.
save_copy() {
    local src=$1 dest
    [ -e "$src" ] || [ -L "$src" ] || return 0
    dest=$(backup_dir)
    run mkdir -p -- "$dest"
    run cp -a -- "$src" "$dest/$(printf '%s' "${src#"$HOME"/}" | tr '/' '_')"
}

ensure_dir() {
    if [ -d "$1" ]; then
        return 0
    fi
    run mkdir -p -- "$1"
    change "created directory $1"
}

# ensure_dir_reported <dir> - like ensure_dir, but also reports an existing dir.
ensure_dir_reported() {
    if [ -d "$1" ]; then
        ok "$1"
        return 0
    fi
    ensure_dir "$1"
}

# link_into <target> <link> - make <link> a symlink to <target>.
# An existing correct link is left alone. Anything else is backed up first.
link_into() {
    local target=$1 link=$2 current
    [ -e "$target" ] || die "link target does not exist: $target"
    if [ -L "$link" ]; then
        current=$(readlink -f -- "$link" 2>/dev/null || true)
        if [ "$current" = "$(readlink -f -- "$target")" ]; then
            ok "$link -> $target"
            return 0
        fi
        save_copy "$link"
        run rm -f -- "$link"
    elif [ -e "$link" ]; then
        save_copy "$link"
        warn "$link was a real path; a copy is in $(backup_dir)"
        run rm -rf -- "$link"
    fi
    ensure_dir "$(dirname -- "$link")"
    run ln -s -- "$target" "$link"
    change "$link -> $target"
}

# install_file <src> <dest> [mode] - copy only when the content differs.
install_file() {
    local src=$1 dest=$2 mode=${3:-0644}
    if [ -f "$dest" ] && cmp -s -- "$src" "$dest"; then
        ok "$dest"
        return 0
    fi
    save_copy "$dest"
    ensure_dir "$(dirname -- "$dest")"
    run cp -- "$src" "$dest"
    run chmod "$mode" -- "$dest"
    change "$dest"
}

# install_if_absent <src> <dest> - never overwrite an existing file.
install_if_absent() {
    local src=$1 dest=$2
    if [ -e "$dest" ]; then
        ok "$dest (already present, left unchanged)"
        return 0
    fi
    ensure_dir "$(dirname -- "$dest")"
    run cp -- "$src" "$dest"
    change "$dest (from template)"
}

summary() {
    printf '\n%s== summary ==%s\n' "$BOLD" "$RESET"
    printf 'changed        %d\nalready ok     %d\n' "$CHANGED" "$SKIPPED"
    if [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ]; then
        printf 'backups        %s\n' "$BACKUP_DIR"
    fi
    if [ "${#MANUAL[@]}" -gt 0 ]; then
        printf '\n%sManual steps that remain:%s\n' "$BOLD" "$RESET"
        local m
        for m in "${MANUAL[@]}"; do printf '  - %s\n' "$m"; done
    fi
}
