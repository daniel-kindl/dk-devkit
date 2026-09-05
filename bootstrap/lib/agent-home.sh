# Host-side agent home preferences.
# Source this file; do not execute it. It needs bootstrap/lib/common.sh.
#
# Orca points CODEX_HOME at a HOST path that is bind-mounted into the box, so
# the host ~/.codex is a real Codex home. It needs the shared policy file, the
# shared status line and the non-secret preference defaults. None of them is a
# credential.

# install_host_agent_home <repo-root> [home]
install_host_agent_home() {
    local repo_root=$1
    local home=${2:-$HOME}

    section 'Codex host preferences (~/.codex/config.toml)'
    ensure_dir "$home/.codex"
    if [ "$DRY_RUN" = 1 ]; then
        info "would merge $repo_root/config/codex/config.base.toml into $home/.codex/config.toml"
    else
        python3 "$repo_root/bin/merge-toml-defaults.py" \
            "$home/.codex/config.toml" "$repo_root/config/codex/config.base.toml"
    fi

    section 'Codex host policy and status line'
    # Codex reads its global instructions from $CODEX_HOME/AGENTS.md. The host
    # Codex home therefore needs the same shared policy file as the one inside
    # the container, and the same status line item list.
    link_into "$repo_root/config/agents/AGENTS.md" "$home/.codex/AGENTS.md"
    if [ "$DRY_RUN" = 1 ]; then
        info 'would apply the shared status line to the host Codex home'
    else
        SPEC_DIR="$repo_root/config/agents/statusline" \
        CODEX_CONFIG="$home/.codex/config.toml" \
        AGENT_BACKUP_DIR="$(backup_dir)" \
            "$repo_root/config/agents/statusline/install.sh" --codex-only |
            sed 's/^/  /'
    fi
}
