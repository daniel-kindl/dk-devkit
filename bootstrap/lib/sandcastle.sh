# Host-side installation of the Sandcastle agent orchestration (agentbox).
# Source this file; do not execute it. It needs bootstrap/lib/common.sh.
#
# It is a separate function so that its idempotency can be exercised on its
# own, without running the whole host bootstrap.

# install_agentbox <repo-root> [home]
#
# Wires agentbox into ~/.local/bin and prepares the credential file location.
# It never writes a credential, and it never builds an image: an image build
# needs the network and takes minutes, so it stays an explicit command.
install_agentbox() {
    local repo_root=$1
    local home=${2:-$HOME}

    link_into "$repo_root/bin/agentbox" "$home/.local/bin/agentbox"

    # The credential file lives outside this repository, and only the user may
    # read it. bootstrap creates the directory and a commented template; the
    # values stay a manual step, exactly like gh and claude authentication.
    local secrets_dir=$home/.config/agentbox
    local secrets_file=$secrets_dir/secrets.env
    ensure_dir "$secrets_dir"
    run chmod 700 -- "$secrets_dir"

    if [ -e "$secrets_file" ]; then
        ok "$secrets_file (already present, left unchanged)"
    elif [ "$DRY_RUN" = 1 ]; then
        info "would create the credential template $secrets_file"
    else
        cat > "$secrets_file" <<'TEMPLATE'
# Credentials for unattended agent runs. NEVER commit this file.
#
# Claude, required. Mint a long-lived token on the host with:
#     claude setup-token
# This is a dedicated token for unattended use. Do not paste the token from an
# interactive session here.
#CLAUDE_CODE_OAUTH_TOKEN=

# Claude, alternative. Use an API key instead of the subscription token.
#ANTHROPIC_API_KEY=

# Codex, optional. Without it, agentbox skips the independent review step.
# The interactive ~/.codex/auth.json is deliberately NOT used: it is a full
# ChatGPT sign-in, which is far more than a disposable sandbox should hold.
#OPENAI_API_KEY=
TEMPLATE
        chmod 600 -- "$secrets_file"
        change "$secrets_file (credential template, mode 600)"
    fi

    # A pre-existing file with loose permissions is a real finding, not a nit.
    if [ -f "$secrets_file" ] && [ "$DRY_RUN" != 1 ]; then
        local mode
        mode=$(stat -c '%a' "$secrets_file" 2>/dev/null || printf '600')
        case $mode in
            600|400) ;;
            *) warn "$secrets_file has mode $mode; tightening it to 600"
               chmod 600 -- "$secrets_file"
               change "$secrets_file mode 600" ;;
        esac
    fi
}
