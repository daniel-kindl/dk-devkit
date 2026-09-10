#!/usr/bin/env bash
#
# Bootstrap the reusable golang-dev Distrobox.
# Run this inside golang-dev through devbox.

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=lib/common.sh
. "$REPO_ROOT/bootstrap/lib/common.sh"

SKIP_SKILLS=0
while [ $# -gt 0 ]; do
    case $1 in
        --dry-run) DRY_RUN=1; shift ;;
        --skip-skills) SKIP_SKILLS=1; shift ;;
        -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
        *) die "unknown option: $1" ;;
    esac
done

if [ ! -f /run/.containerenv ] && [ ! -f /.dockerenv ]; then
    die 'this bootstrap must run inside the golang-dev container, not on the host'
fi

# shellcheck source=../manifests/golang-dev.env
. "$REPO_ROOT/manifests/golang-dev.env"
# shellcheck source=../manifests/toolchain.env
. "$REPO_ROOT/manifests/toolchain.env"

export GOPATH="$HOME/$GO_PATH_REL"
export PATH="$GOPATH/bin:$HOME/.local/bin${PATH:+:$PATH}"

LINK_ROOT=$REPO_ROOT
if [ -n "${DISTROBOX_HOST_HOME:-}" ]; then
    candidate=${REPO_ROOT/#\/workspace/$DISTROBOX_HOST_HOME/projects}
    if [ "$candidate" != "$REPO_ROOT" ] && [ -e "$candidate" ] && [ "$candidate" -ef "$REPO_ROOT" ]; then
        LINK_ROOT=$candidate
    fi
fi

printf '%sgol-devkit golang-dev bootstrap%s\n' "$BOLD" "$RESET"
info "checkout   $REPO_ROOT"
info "link root  $LINK_ROOT"
info "box home   $HOME"
info "GOPATH     $GOPATH"
[ "$DRY_RUN" = 1 ] && info 'DRY RUN - nothing is written'

section 'Distribution packages'
missing=()
while read -r pkg; do
    case ${pkg:-} in ''|'#'*) continue ;; esac
    rpm -q "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
done < <(sed -e 's/#.*//' "$REPO_ROOT/manifests/golang-dev-packages.txt" | awk 'NF')
[ "${#missing[@]}" -eq 0 ] || run sudo dnf install -y "${missing[@]}"

section 'Shell integration'
ensure_dir "$HOME/.bashrc.d"
install_file "$REPO_ROOT/config/golang-dev/bashrc.d/10-golang-dev.sh" \
    "$HOME/.bashrc.d/10-golang-dev.sh" 0644

section 'Go toolchain'
check_go=$(command -v go || true)
if [ -n "$check_go" ]; then
    ok "Go $(go version | awk '{print $3}')"
elif [ "$DRY_RUN" = 1 ]; then
    info 'would install Go from the golang distribution package'
else
    die 'Go is not available after package installation'
fi

section 'Go dependency ownership'
ok 'modules remain repository-owned through go.mod and go.sum'

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
link_into "$LINK_ROOT/config/golang-dev/bin/orca-ide" "$HOME/.local/bin/orca-ide"
link_into "$LINK_ROOT/config/golang-dev/bin/orca-ide" "$HOME/.local/bin/orca"

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

manual 'Authenticate Claude Code in golang-dev: claude (then /login)'
manual 'Authenticate Codex in golang-dev: codex login'
manual 'Authenticate GitHub in golang-dev: gh auth login --git-protocol ssh --skip-ssh-key'
manual 'Verify the environment: ./verify.sh --only 28'
summary
