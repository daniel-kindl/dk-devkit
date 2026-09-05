# Installation of the GitHub backlog coordinator (agentqueue).
# Source this file; do not execute it. It needs bootstrap/lib/common.sh.
#
# agentqueue belongs in the CONTAINER, not on the host. It needs gh, and gh
# lives in web-dev. The host keeps no Node toolchain and no gh, so a host shim
# would only be able to report that it cannot run.

# install_agentqueue <repo-root> <link-root> [home]
#
# Links the command into ~/.local/bin and creates the run scratch area. It
# writes no policy file: a policy belongs to the repository it governs, and
# "agentqueue init" writes one on request.
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
