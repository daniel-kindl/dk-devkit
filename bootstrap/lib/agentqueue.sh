# Installation of the GitHub backlog coordinator (agentqueue).
# Source this file; do not execute it. It needs bootstrap/lib/common.sh.
#
# The coordinator runs in the CONTAINER, not on the host. It needs gh, and gh
# lives in web-dev. The host keeps no Node toolchain and no gh.
#
# The host still gets the COMMAND, because that is the documented user
# interface. It is a router shim: no runtime, no credential, no state. It
# translates the working directory and delegates to the coordinator inside the
# environment that manifests/agentqueue.env names.
#
#   host                          container
#   ~/.local/bin/agentqueue  -->  devbox exec <env> --cwd $PWD -- agentqueue
#   (a shim, 20 lines)            (the real Python program)

# agentqueue_environment <repo-root>
#
# The environment that owns the runtime, read from the manifest. One value
# drives both halves of the installation.
agentqueue_environment() {
    local value
    value=$(sed -n 's/^AGENTQUEUE_ENVIRONMENT=//p' "$1/manifests/agentqueue.env" |
            head -1 | tr -d '"'"'"' \t\r')
    [ -n "$value" ] ||
        die "manifests/agentqueue.env does not set AGENTQUEUE_ENVIRONMENT"
    printf '%s' "$value"
}

# install_agentqueue <repo-root> <link-root> [home]
#
# The CONTAINER half. Links the command into ~/.local/bin and creates the run
# scratch area. It writes no policy file: a policy belongs to the repository it
# governs, and "agentqueue init" writes one on request.
install_agentqueue() {
    local repo_root=$1
    local link_root=$2
    local home=${3:-$HOME}

    link_into "$link_root/bin/agentqueue" "$home/.local/bin/agentqueue"

    # Prompts, agentbox logs and per-issue locks. It holds no credential: the
    # GitHub token stays in the gh keyring, and the model credential stays in
    # the agentbox credential file, which agentqueue never reads.
    local state_dir=$home/.local/share/agentqueue
    ensure_dir "$state_dir"
    run chmod 700 -- "$state_dir"

    # A machine-local policy, for a repository that cannot carry
    # .agentqueue.json yet. The directory is created; nothing is written into
    # it.
    ensure_dir "$home/.config/agentqueue/repos"
}

# install_agentqueue_host_shim <repo-root> [home]
#
# The HOST half. The router generates the text, so the shim can never drift
# from the router that consumes it.
#
# Unlike the claude and codex shims, this one is REFRESHED and not only
# created: its text names the environment that owns the runtime, so it carries
# configuration, and stale configuration must not survive a bootstrap. Anything
# it replaces is copied into the backup directory first.
install_agentqueue_host_shim() {
    local repo_root=$1
    local home=${2:-$HOME}
    local env tmp dest=$home/.local/bin/agentqueue rc=0

    env=$(agentqueue_environment "$repo_root")
    info "pinned to the $env environment (manifests/agentqueue.env)"

    tmp=$(mktemp) || die 'cannot create a temporary file'
    "$repo_root/bin/devbox" new-shim agentqueue --env "$env" --print > "$tmp" || rc=$?
    if [ "$rc" != 0 ]; then
        rm -f -- "$tmp"
        die "the devbox router could not generate the agentqueue host shim (exit $rc)"
    fi
    install_file "$tmp" "$dest" 0755
    rm -f -- "$tmp"
}
