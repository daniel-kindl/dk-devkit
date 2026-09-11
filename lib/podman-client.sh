# The Podman client that bin/agentbox and bin/agent-sandbox use.
# Source this file; do not execute it. The caller sets IN_CONTAINER to 1 inside
# a container and to 0 on the host.
#
# On the host this is plain "podman". Inside a container there is no local
# engine, so it is podman-remote pointed at the rootless host API socket. Both
# reach the same daemon, and a container created either way is a host-level
# sibling of the caller.

PODMAN_SOCKET=${PODMAN_SOCKET:-${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/podman/podman.sock}
PODMAN_BIN=''

# resolve_podman - set PODMAN_BIN, and CONTAINER_HOST when the engine is remote.
#
# It only reports: it returns 1 when there is no client, and it never exits.
resolve_podman() {
    [ -n "$PODMAN_BIN" ] && return 0
    if [ "$IN_CONTAINER" = 0 ] && command -v podman >/dev/null 2>&1; then
        PODMAN_BIN=$(command -v podman)
        return 0
    fi
    if command -v podman-remote >/dev/null 2>&1; then
        PODMAN_BIN=$(command -v podman-remote)
        export CONTAINER_HOST="unix://$PODMAN_SOCKET"
        return 0
    fi
    if command -v podman >/dev/null 2>&1; then
        PODMAN_BIN=$(command -v podman)
        export CONTAINER_HOST="unix://$PODMAN_SOCKET"
        return 0
    fi
    return 1
}
