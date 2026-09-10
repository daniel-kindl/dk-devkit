#!/usr/bin/env bash
#
# Bootstrap the reusable dotnet-dev Distrobox.
# Run this inside dotnet-dev through devbox.

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=lib/common.sh
. "$REPO_ROOT/bootstrap/lib/common.sh"

SKIP_SKILLS=0
while [ $# -gt 0 ]; do
    case $1 in
        --dry-run) DRY_RUN=1; shift ;;
        --skip-skills) SKIP_SKILLS=1; shift ;;
        -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
        *) die "unknown option: $1" ;;
    esac
done

if [ ! -f /run/.containerenv ] && [ ! -f /.dockerenv ]; then
    die 'this bootstrap must run inside the dotnet-dev container, not on the host'
fi

# shellcheck source=../manifests/dotnet-dev.env
. "$REPO_ROOT/manifests/dotnet-dev.env"
# shellcheck source=../manifests/toolchain.env
. "$REPO_ROOT/manifests/toolchain.env"

export DOTNET_CLI_HOME="$HOME/$DOTNET_CLI_HOME_REL"
export PATH="$HOME/.local/bin${PATH:+:$PATH}"

LINK_ROOT=$REPO_ROOT
if [ -n "${DISTROBOX_HOST_HOME:-}" ]; then
    candidate=${REPO_ROOT/#\/workspace/$DISTROBOX_HOST_HOME/projects}
    if [ "$candidate" != "$REPO_ROOT" ] && [ -e "$candidate" ] && [ "$candidate" -ef "$REPO_ROOT" ]; then
        LINK_ROOT=$candidate
    fi
fi

printf '%sdk-devkit dotnet-dev bootstrap%s\n' "$BOLD" "$RESET"
info "checkout   $REPO_ROOT"
info "link root  $LINK_ROOT"
info "box home   $HOME"
info "DOTNET_CLI_HOME $DOTNET_CLI_HOME"
[ "$DRY_RUN" = 1 ] && info 'DRY RUN - nothing is written'

section 'Distribution packages'
missing=()
while read -r pkg; do
    [ -n "${pkg:-}" ] || continue
    rpm -q "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
done < <(sed -e 's/#.*//' "$REPO_ROOT/manifests/dotnet-dev-packages.txt" | awk 'NF')
[ "${#missing[@]}" -eq 0 ] || run sudo dnf install -y "${missing[@]}"

section 'Shell integration'
ensure_dir "$HOME/.bashrc.d"
install_file "$REPO_ROOT/config/dotnet-dev/bashrc.d/10-dotnet-dev.sh" \
    "$HOME/.bashrc.d/10-dotnet-dev.sh" 0644

section '.NET SDK'
if command -v dotnet >/dev/null 2>&1; then
    ok "$(dotnet --version)"
elif [ "$DRY_RUN" = 1 ]; then
    info 'would install the .NET SDK from the distribution package'
else
    die '.NET SDK is not available after package installation'
fi

section 'Agent CLIs'
if [ -x "$HOME/.local/bin/claude" ]; then
    ok "claude ($("$HOME/.local/bin/claude" --version 2>/dev/null | head -1))"
else
    run bash -c "curl -fsSL $CLAUDE_CODE_INSTALLER | bash" && change 'installed Claude Code'
fi
if [ -x "$HOME/.local/bin/codex" ]; then
    ok "codex ($("$HOME/.local/bin/codex" --version 2>/dev/null | head -1))"
else
    run bash -c "curl -fsSL $CODEX_INSTALLER | sh" && change 'installed Codex'
fi

section 'Shared agent configuration (~/.agents)'
ensure_dir_reported "$HOME/.agents"
ensure_dir "$HOME/.agents/skills"
link_into "$LINK_ROOT/config/agents/AGENTS.md" "$HOME/.agents/AGENTS.md"
link_into "$LINK_ROOT/config/agents/statusline" "$HOME/.agents/statusline"

section 'Client wiring'
ensure_dir "$HOME/.claude"
ensure_dir "$HOME/.codex"
link_into "$HOME/.agents/AGENTS.md" "$HOME/.claude/CLAUDE.md"
link_into "$HOME/.agents/AGENTS.md" "$HOME/.codex/AGENTS.md"
link_into "$HOME/.agents/skills" "$HOME/.claude/skills"

section 'Local commands (~/.local/bin)'
ensure_dir "$HOME/.local/bin"
link_into "$LINK_ROOT/bin/sync-agent-skills" "$HOME/.local/bin/sync-agent-skills"
link_into "$LINK_ROOT/config/dotnet-dev/bin/orca-ide" "$HOME/.local/bin/orca-ide"
link_into "$LINK_ROOT/config/dotnet-dev/bin/orca-ide" "$HOME/.local/bin/orca"

section 'Third-party skills'
if [ "$SKIP_SKILLS" = 1 ]; then
    info 'skipped (--skip-skills)'
elif [ "$DRY_RUN" = 1 ]; then
    info 'would run bin/install-skills against manifests/skills.tsv'
else
    "$REPO_ROOT/bin/install-skills"
fi

section 'Client preferences'
if [ "$DRY_RUN" = 1 ]; then
    info "would merge shared client preferences into $HOME"
else
    [ -f "$HOME/.claude/settings.json" ] || printf '{}\n' > "$HOME/.claude/settings.json"
    python3 "$REPO_ROOT/bin/merge-json-defaults.py" \
        "$HOME/.claude/settings.json" "$REPO_ROOT/config/claude/settings.base.json"
    python3 "$REPO_ROOT/bin/merge-toml-defaults.py" \
        "$HOME/.codex/config.toml" "$REPO_ROOT/config/codex/config.base.toml"
    "$HOME/.agents/statusline/install.sh"
fi

manual 'Authenticate Claude Code in dotnet-dev: claude (then /login)'
manual 'Authenticate Codex in dotnet-dev: codex login'
manual 'Authenticate GitHub in dotnet-dev: gh auth login --git-protocol ssh --skip-ssh-key'
manual 'Verify the environment: ./verify.sh --only 29'
summary
