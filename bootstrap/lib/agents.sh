# Interactive agent CLIs inside a development environment.
# Source this file; do not execute it. It needs bootstrap/lib/common.sh
# and the installer URLs from manifests/toolchain.env.
#
# Claude Code, Codex and Grok are native installers. The bootstrap installs
# missing CLIs and asks each installed CLI to update itself.

# install_one_agent <binary> <name> <shell> <installer-url>
install_one_agent() {
    local bin=$1 name=$2 shell=$3 installer=$4
    local version

    if [ -x "$bin" ]; then
        version=$("$bin" --version 2>/dev/null | head -1)
        ok "$name ($version)"
        if [ "${DRY_RUN:-0}" = 1 ]; then
            info "would update $name"
        else
            "$bin" update || die "$name update failed"
        fi
        return 0
    fi
    [ -n "$installer" ] || die "no installer URL for $name"
    run bash -c "curl -fsSL $installer | $shell" && change "installed $name"
}

# install_agent_clis
#
# Installs Claude Code, Codex and Grok into this environment HOME.
# The host command of the same name is a router shim. This function
# installs the real binary, and it makes ~/.local/bin/grok point at it.
# The upstream Grok installer also links the name "agent" in this HOME.
# That name stays inside the environment. The host does not get it.
install_agent_clis() {
    section 'Agent CLIs'
    [ -n "${CLAUDE_CODE_INSTALLER:-}" ] || die 'CLAUDE_CODE_INSTALLER is not set'
    [ -n "${CODEX_INSTALLER:-}" ] || die 'CODEX_INSTALLER is not set'
    [ -n "${GROK_INSTALLER:-}" ] || die 'GROK_INSTALLER is not set'

    install_one_agent "$HOME/.local/bin/claude" claude bash "$CLAUDE_CODE_INSTALLER"
    install_one_agent "$HOME/.local/bin/codex"  codex  sh   "$CODEX_INSTALLER"
    install_one_agent "$HOME/.grok/bin/grok"    grok   bash "$GROK_INSTALLER"

    if [ "${DRY_RUN:-0}" = 1 ]; then
        info "would set bypass permission mode for Claude Code, Codex and Grok"
    else
        python3 "$REPO_ROOT/bin/set-agent-modes.py" "$HOME"
    fi

    if [ -x "$HOME/.grok/bin/grok" ]; then
        link_into "$HOME/.grok/bin/grok" "$HOME/.local/bin/grok"
        return 0
    fi
    if [ "$DRY_RUN" = 1 ]; then
        info "would link $HOME/.local/bin/grok to $HOME/.grok/bin/grok after Grok is installed"
    fi
}
