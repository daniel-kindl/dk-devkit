#!/usr/bin/env bash
#
# Bootstrap the reusable python-dev Distrobox.
# Run this INSIDE python-dev:
#
#   devbox exec python-dev --cwd ~/projects/dk-devkit -- ./bootstrap/python-dev.sh
#
# The environment owns generic Python tooling only. A repository owns its
# Python version and dependencies through uv.

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=lib/common.sh
. "$REPO_ROOT/bootstrap/lib/common.sh"

SKIP_SKILLS=0
while [ $# -gt 0 ]; do
    case $1 in
        --dry-run) DRY_RUN=1; shift ;;
        --skip-skills) SKIP_SKILLS=1; shift ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) die "unknown option: $1" ;;
    esac
done

if [ ! -f /run/.containerenv ] && [ ! -f /.dockerenv ]; then
    die "this bootstrap must run INSIDE the python-dev container, not on the host"
fi

# shellcheck source=../manifests/python-dev.env
. "$REPO_ROOT/manifests/python-dev.env"
# Agent installer URLs are currently shared with web-dev in this manifest.
# shellcheck source=../manifests/toolchain.env
. "$REPO_ROOT/manifests/toolchain.env"

# Use the host spelling for live symlink targets when this checkout is mounted
# at /workspace. The same file can then be inspected from either side.
LINK_ROOT=$REPO_ROOT
if [ -n "${DISTROBOX_HOST_HOME:-}" ]; then
    candidate=${REPO_ROOT/#\/workspace/$DISTROBOX_HOST_HOME/projects}
    if [ "$candidate" != "$REPO_ROOT" ] && [ -e "$candidate" ] && [ "$candidate" -ef "$REPO_ROOT" ]; then
        LINK_ROOT=$candidate
    fi
fi

printf '%sworkstation python-dev bootstrap%s\n' "$BOLD" "$RESET"
info "checkout   $REPO_ROOT"
info "link root  $LINK_ROOT"
info "box home   $HOME"
info "uv         $UV_VERSION"
info 'python     project-owned through uv'
[ "$DRY_RUN" = 1 ] && info "DRY RUN - nothing is written"

# ----------------------------------------------------------------- packages --
section 'Distribution packages'
missing=()
while read -r pkg; do
    case ${pkg:-} in ''|'#'*) continue ;; esac
    if rpm -q "$pkg" >/dev/null 2>&1; then ok "$pkg"; else missing+=("$pkg"); fi
done < <(sed -e 's/#.*//' "$REPO_ROOT/manifests/python-dev-packages.txt" | awk 'NF')
if [ "${#missing[@]}" -gt 0 ]; then
    run sudo dnf install -y "${missing[@]}" && change "installed ${missing[*]}"
fi

# ------------------------------------------------------------- shell / PATH --
section 'Shell integration'
ensure_dir "$HOME/.bashrc.d"
install_file "$REPO_ROOT/config/python-dev/bashrc.d/10-python-dev.sh" \
    "$HOME/.bashrc.d/10-python-dev.sh" 0644
export PATH="$HOME/.local/bin${PATH:+:$PATH}"

# ----------------------------------------------------------------------- uv --
section "uv $UV_VERSION"
uv_current=''
if [ -x "$HOME/.local/bin/uv" ]; then
    uv_current=$("$HOME/.local/bin/uv" --version 2>/dev/null | awk '{print $2}')
fi
if [ "$uv_current" = "$UV_VERSION" ]; then
    ok "uv $UV_VERSION"
elif [ "$DRY_RUN" = 1 ]; then
    info "would install uv $UV_VERSION into $HOME/.local/bin"
else
    export UV_NO_MODIFY_PATH=1
    curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | sh
    unset UV_NO_MODIFY_PATH
    uv_current=$("$HOME/.local/bin/uv" --version 2>/dev/null | awk '{print $2}')
    [ "$uv_current" = "$UV_VERSION" ] || die "uv install returned version ${uv_current:-unknown}; expected $UV_VERSION"
    change "installed uv $UV_VERSION"
fi

# The container does not install a default Python. A project pin such as
# `.python-version` or `requires-python` causes uv to select/install the needed
# interpreter in this isolated HOME.
section 'Python ownership'
if grep -Eq '^[[:space:]]*PYTHON_VERSION=' "$REPO_ROOT/manifests/python-dev.env"; then
    die 'python-dev must not pin a project Python version in its environment manifest'
fi
ok 'Python version remains repository-owned through uv'

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
link_into "$LINK_ROOT/bin/sync-agent-skills"          "$HOME/.local/bin/sync-agent-skills"
link_into "$LINK_ROOT/config/python-dev/bin/orca-ide" "$HOME/.local/bin/orca-ide"
link_into "$LINK_ROOT/config/python-dev/bin/orca-ide" "$HOME/.local/bin/orca"

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

section 'Status line'
if [ "$DRY_RUN" = 1 ]; then
    info 'would run ~/.agents/statusline/install.sh'
else
    "$HOME/.agents/statusline/install.sh"
fi

manual 'Authenticate Claude Code in python-dev: claude  (then /login)'
manual 'Authenticate Codex in python-dev: codex login'
manual 'Authenticate GitHub in python-dev: gh auth login --git-protocol ssh --skip-ssh-key'
manual 'Pin Python in each project with pyproject.toml and/or .python-version'
manual 'Verify the environment: ./verify.sh --only 25'

summary
