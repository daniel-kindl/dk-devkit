# Creation of a Distrobox development environment.
# Source this file; do not execute it. It needs bootstrap/lib/common.sh.
#
# One function creates one environment. An existing container is never
# touched: recreating one deliberately is docs/recovery.md.

# create_development_environment <repo-root> <name>
#
# Creates the named container from distrobox/<name>.ini when it is absent.
create_development_environment() {
    local repo_root=$1 name=$2

    if ! have distrobox; then
        # One report, however many environments the caller asks for.
        if [ "${DISTROBOX_REPORTED_MISSING:-0}" != 1 ]; then
            DISTROBOX_REPORTED_MISSING=1
            warn 'distrobox is not installed'
            manual 'Install distrobox on the host, then re-run the installer'
        fi
        return 0
    fi
    if podman container exists "$name" 2>/dev/null; then
        ok "container $name already exists (left untouched)"
        return 0
    fi
    run distrobox assemble create --file "$repo_root/distrobox/$name.ini" &&
        change "created container $name"
}
