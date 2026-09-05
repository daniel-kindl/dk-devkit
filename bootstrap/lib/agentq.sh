# Installation of the trusted GitHub backlog coordinator (agentq).
# Source this file; do not execute it. It needs bootstrap/lib/common.sh.
#
# The coordinator runtime runs in the CONTAINER, not on the host. It needs gh,
# and gh lives in web-dev. The host still gets the supported `agentq` command
# as a router shim with no runtime, credential, or state of its own.
#
# The manifest and AGENTQUEUE_* variable names are deliberately preserved as
# durable internal configuration identifiers during this CLI rename.
#
#   host                      container
#   ~/.local/bin/agentq  -->  devbox exec <env> --cwd $PWD -- agentq
#   (router shim)             (real Python program)

agentq_environment() {
    local value
    value=$(sed -n 's/^AGENTQUEUE_ENVIRONMENT=//p' "$1/manifests/agentqueue.env" |
            head -1 | tr -d '"'"'"' \t\r')
    [ -n "$value" ] ||
        die "manifests/agentqueue.env does not set AGENTQUEUE_ENVIRONMENT"
    printf '%s' "$value"
}

agentq_path_options() {
    sed -n 's/^AGENTQUEUE_HOST_PATH_OPTIONS=//p' "$1/manifests/agentqueue.env" |
        head -1 | tr -d '"'"'"' \t\r'
}

agentq_shim_args() {
    local opts option
    printf '%s\n' agentq --env "$2"
    opts=$(agentq_path_options "$1")
    if [ -n "$opts" ]; then
        printf '%s\n' "$opts" | tr ',' '\n' | while IFS= read -r option; do
            [ -n "$option" ] && printf '%s\n%s\n' --map-path "$option"
        done
    fi
    printf '%s\n' --print
}

remove_obsolete_agentqueue_command() {
    local home=$1
    local obsolete=$home/.local/bin/agentqueue
    if [ -e "$obsolete" ] || [ -L "$obsolete" ]; then
        if [ "${DRY_RUN:-0}" = 1 ]; then
            info "would remove obsolete $obsolete"
        else
            rm -f -- "$obsolete"
            change "removed obsolete $obsolete"
        fi
    fi
}

# install_agentq <repo-root> <link-root> [home]
#
# Install the real container-side command. State/config directories retain
# their historical internal names so existing runs and repository policy do
# not migrate merely because the executable became shorter.
install_agentq() {
    local repo_root=$1
    local link_root=$2
    local home=${3:-$HOME}

    link_into "$link_root/bin/agentq" "$home/.local/bin/agentq"
    remove_obsolete_agentqueue_command "$home"

    local state_dir=$home/.local/share/agentqueue
    ensure_dir "$state_dir"
    run chmod 700 -- "$state_dir"

    ensure_dir "$home/.config/agentqueue/repos"
}

# install_agentq_host_shim <repo-root> [home]
install_agentq_host_shim() {
    local repo_root=$1
    local home=${2:-$HOME}
    local env opts tmp dest=$home/.local/bin/agentq rc=0
    local shim_args=()

    env=$(agentq_environment "$repo_root")
    info "pinned to the $env environment (manifests/agentqueue.env)"
    opts=$(agentq_path_options "$repo_root")
    [ -n "$opts" ] && info "the router translates $opts into the container"

    mapfile -t shim_args < <(agentq_shim_args "$repo_root" "$env")
    tmp=$(mktemp) || die 'cannot create a temporary file'
    "$repo_root/bin/devbox" new-shim "${shim_args[@]}" > "$tmp" || rc=$?
    if [ "$rc" != 0 ]; then
        rm -f -- "$tmp"
        die "the devbox router could not generate the agentq host shim (exit $rc)"
    fi
    install_file "$tmp" "$dest" 0755
    rm -f -- "$tmp"

    # Clean-break command rename: convergence removes the obsolete executable
    # rather than leaving an alias or compatibility wrapper behind.
    remove_obsolete_agentqueue_command "$home"
}
