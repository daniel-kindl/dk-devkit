#!/usr/bin/env bash
#
# Bootstrap the web-dev Distrobox half of the workstation.
# Run this INSIDE the container:
#
#   devbox exec web-dev --cwd ~/projects/workstation -- ./bootstrap/web-dev.sh
#
# What it does, all idempotently:
#   * installs the distribution packages in manifests/web-dev-packages.txt
#   * installs nvm, Node, Corepack and pnpm at the versions in manifests/toolchain.env
#   * installs the Claude Code and Codex native CLIs when they are absent
#   * wires the shared agent configuration into ~/.agents, ~/.claude and ~/.codex
#   * installs the Orca bridge wrappers and sync-agent-skills
#   * installs the third-party skills in manifests/skills.tsv
#   * applies the shared status line specification
#
# What it never does:
#   * write any credential: authentication stays a manual step
#   * remove a Codex native skill from ~/.codex/skills/.system
#   * overwrite Orca's hooks in ~/.claude/settings.json

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=lib/common.sh
. "$REPO_ROOT/bootstrap/lib/common.sh"

SKIP_SKILLS=0
while [ $# -gt 0 ]; do
    case $1 in
        --dry-run) DRY_RUN=1; shift ;;
        --skip-skills) SKIP_SKILLS=1; shift ;;
        -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
        *) die "unknown option: $1" ;;
    esac
done

if [ ! -f /run/.containerenv ] && [ ! -f /.dockerenv ]; then
    die "this bootstrap must run INSIDE the web-dev container, not on the host"
fi

# shellcheck source=../manifests/toolchain.env
. "$REPO_ROOT/manifests/toolchain.env"
NVM_DIR="$HOME/$NVM_DIR_REL"

# Symlink targets use the HOST spelling of the checkout, not /workspace.
# Both spellings reach the same files inside the box, but only the host
# spelling also resolves when the links are inspected from the host, which is
# what lets ./verify.sh run from either side.
LINK_ROOT=$REPO_ROOT
if [ -n "${DISTROBOX_HOST_HOME:-}" ]; then
    candidate=${REPO_ROOT/#\/workspace/$DISTROBOX_HOST_HOME/projects}
    if [ "$candidate" != "$REPO_ROOT" ] && [ -e "$candidate" ] && [ "$candidate" -ef "$REPO_ROOT" ]; then
        LINK_ROOT=$candidate
    fi
fi

printf '%sworkstation web-dev bootstrap%s\n' "$BOLD" "$RESET"
info "checkout   $REPO_ROOT"
info "link root  $LINK_ROOT"
info "box home   $HOME"
info "node       $NODE_VERSION   pnpm $PNPM_VERSION   corepack $COREPACK_VERSION"
[ "$DRY_RUN" = 1 ] && info "DRY RUN - nothing is written"

# ----------------------------------------------------------------- packages --
section 'Distribution packages'
missing=()
while read -r pkg; do
    case ${pkg:-} in ''|'#'*) continue ;; esac
    if rpm -q "$pkg" >/dev/null 2>&1; then ok "$pkg"; else missing+=("$pkg"); fi
done < <(sed -e 's/#.*//' "$REPO_ROOT/manifests/web-dev-packages.txt" | awk 'NF')
if [ "${#missing[@]}" -gt 0 ]; then
    run sudo dnf install -y "${missing[@]}" && change "installed ${missing[*]}"
fi

# ---------------------------------------------------------------------- nvm --
section "nvm $NVM_VERSION (NVM_DIR=$NVM_DIR)"
if [ -s "$NVM_DIR/nvm.sh" ]; then
    ok "$NVM_DIR/nvm.sh"
else
    run env NVM_DIR="$NVM_DIR" bash -c \
        "curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v$NVM_VERSION/install.sh | PROFILE=/dev/null bash" &&
        change "installed nvm $NVM_VERSION"
fi

section 'Shell integration'
# The stock Fedora ~/.bashrc already sources ~/.bashrc.d/*. Only add the
# fragment when nvm is not configured yet, so an existing inline block in
# ~/.bashrc is preserved and nvm is never loaded twice.
if grep -q 'NVM_DIR' "$HOME/.bashrc" 2>/dev/null; then
    ok '~/.bashrc already loads nvm (left unchanged)'
else
    ensure_dir "$HOME/.bashrc.d"
    install_file "$REPO_ROOT/config/web-dev/bashrc.d/10-nvm.sh" "$HOME/.bashrc.d/10-nvm.sh" 0644
fi

# --------------------------------------------------------- Node / pnpm ------
section "Node $NODE_VERSION, Corepack $COREPACK_VERSION, pnpm $PNPM_VERSION"
if [ "$DRY_RUN" = 1 ]; then
    info "would install Node $NODE_VERSION, corepack@$COREPACK_VERSION and pnpm@$PNPM_VERSION"
else
    # One login-style subshell: nvm is a shell function, not an executable.
    toolchain_report=$(
        set -euo pipefail
        export NVM_DIR="$NVM_DIR"
        # shellcheck disable=SC1091
        . "$NVM_DIR/nvm.sh"

        if [ "$(nvm version "$NODE_VERSION" 2>/dev/null)" = "N/A" ]; then
            nvm install "$NODE_VERSION" >&2
            printf 'change\tnode %s installed\n' "$NODE_VERSION"
        else
            printf 'ok\tnode %s\n' "$NODE_VERSION"
        fi
        nvm use "$NODE_VERSION" >/dev/null
        nvm alias default "$NODE_VERSION" >/dev/null

        if [ "$(corepack --version 2>/dev/null || true)" = "$COREPACK_VERSION" ]; then
            printf 'ok\tcorepack %s\n' "$COREPACK_VERSION"
        else
            npm install -g "corepack@$COREPACK_VERSION" >&2
            printf 'change\tcorepack %s installed\n' "$COREPACK_VERSION"
        fi
        corepack enable >&2

        if [ "$(pnpm --version 2>/dev/null || true)" = "$PNPM_VERSION" ]; then
            printf 'ok\tpnpm %s\n' "$PNPM_VERSION"
        else
            corepack prepare "pnpm@$PNPM_VERSION" --activate >&2
            printf 'change\tpnpm %s activated\n' "$PNPM_VERSION"
        fi
    )
    while IFS=$'\t' read -r verdict text; do
        [ -n "${text:-}" ] || continue
        case $verdict in ok) ok "$text" ;; change) change "$text" ;; esac
    done <<< "$toolchain_report"
fi

# ----------------------------------------------------------- agent CLIs -----
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

# ------------------------------------------------- shared agent configuration --
section 'Shared agent configuration (~/.agents)'
ensure_dir_reported "$HOME/.agents"
ensure_dir "$HOME/.agents/skills"
link_into "$LINK_ROOT/config/agents/AGENTS.md"  "$HOME/.agents/AGENTS.md"
link_into "$LINK_ROOT/config/agents/statusline" "$HOME/.agents/statusline"

section 'Client wiring'
ensure_dir "$HOME/.claude"
ensure_dir "$HOME/.codex"
link_into "$HOME/.agents/AGENTS.md" "$HOME/.claude/CLAUDE.md"
link_into "$HOME/.agents/AGENTS.md" "$HOME/.codex/AGENTS.md"
link_into "$HOME/.agents/skills"    "$HOME/.claude/skills"

section 'Local commands (~/.local/bin)'
ensure_dir "$HOME/.local/bin"
link_into "$LINK_ROOT/bin/sync-agent-skills"       "$HOME/.local/bin/sync-agent-skills"
link_into "$LINK_ROOT/config/web-dev/bin/orca-ide" "$HOME/.local/bin/orca-ide"
link_into "$LINK_ROOT/config/web-dev/bin/orca-ide" "$HOME/.local/bin/orca"

# ------------------------------------------------------- third-party skills --
section 'Third-party skills'
if [ "$SKIP_SKILLS" = 1 ]; then
    info 'skipped (--skip-skills)'
elif [ "$DRY_RUN" = 1 ]; then
    info "would run bin/install-skills against manifests/skills.tsv"
else
    "$REPO_ROOT/bin/install-skills"
fi

# -------------------------------------------------------- client preferences --
section 'Claude preferences (~/.claude/settings.json)'
if [ "$DRY_RUN" = 1 ]; then
    info "would merge config/claude/settings.base.json into $HOME/.claude/settings.json"
else
    [ -f "$HOME/.claude/settings.json" ] || printf '{}\n' > "$HOME/.claude/settings.json"
    python3 "$REPO_ROOT/bin/merge-json-defaults.py" \
        "$HOME/.claude/settings.json" "$REPO_ROOT/config/claude/settings.base.json"
fi

section 'Codex preferences ($CODEX_HOME/config.toml)'
if [ "$DRY_RUN" = 1 ]; then
    info "would merge config/codex/config.base.toml into $HOME/.codex/config.toml"
else
    python3 "$REPO_ROOT/bin/merge-toml-defaults.py" \
        "$HOME/.codex/config.toml" "$REPO_ROOT/config/codex/config.base.toml"
fi

# -------------------------------------------------------------- status line --
section 'Status line'
if [ "$DRY_RUN" = 1 ]; then
    info 'would run ~/.agents/statusline/install.sh'
else
    "$HOME/.agents/statusline/install.sh"
fi

# ------------------------------------------------------------ manual steps ---
manual 'Authenticate Claude Code:  claude  (then /login)'
manual 'Authenticate Codex:        codex login'
manual 'Authenticate GitHub in the box: gh auth login --git-protocol ssh'
manual 'Verify the whole workstation: ./verify.sh'

summary
