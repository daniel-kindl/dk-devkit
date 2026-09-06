#!/usr/bin/env bash
#
# Bootstrap the reusable rust-dev Distrobox.
# Run this INSIDE rust-dev:
#
#   devbox exec rust-dev --cwd ~/projects/dk-devkit -- ./bootstrap/rust-dev.sh
#
# The environment owns generic Rust tooling only. A repository owns its
# toolchain through rust-toolchain.toml and its dependencies through Cargo.

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
    die "this bootstrap must run INSIDE the rust-dev container, not on the host"
fi

# shellcheck source=../manifests/rust-dev.env
. "$REPO_ROOT/manifests/rust-dev.env"
# Agent installer URLs are currently shared with web-dev in this manifest.
# shellcheck source=../manifests/toolchain.env
. "$REPO_ROOT/manifests/toolchain.env"

RUSTUP_HOME=$HOME/$RUSTUP_HOME_REL
CARGO_HOME=$HOME/$CARGO_HOME_REL
export RUSTUP_HOME CARGO_HOME

# Use the host spelling for live symlink targets when this checkout is mounted
# at /workspace. The same file can then be inspected from either side.
LINK_ROOT=$REPO_ROOT
if [ -n "${DISTROBOX_HOST_HOME:-}" ]; then
    candidate=${REPO_ROOT/#\/workspace/$DISTROBOX_HOST_HOME/projects}
    if [ "$candidate" != "$REPO_ROOT" ] && [ -e "$candidate" ] && [ "$candidate" -ef "$REPO_ROOT" ]; then
        LINK_ROOT=$candidate
    fi
fi

printf '%sdk-devkit rust-dev bootstrap%s\n' "$BOLD" "$RESET"
info "checkout   $REPO_ROOT"
info "link root  $LINK_ROOT"
info "box home   $HOME"
info "rust       $RUST_VERSION (baseline; a repository may pin its own)"
info "cargo home $CARGO_HOME"
[ "$DRY_RUN" = 1 ] && info "DRY RUN - nothing is written"

# ----------------------------------------------------------------- packages --
section 'Distribution packages'
missing=()
while read -r pkg; do
    case ${pkg:-} in ''|'#'*) continue ;; esac
    if rpm -q "$pkg" >/dev/null 2>&1; then ok "$pkg"; else missing+=("$pkg"); fi
done < <(sed -e 's/#.*//' "$REPO_ROOT/manifests/rust-dev-packages.txt" | awk 'NF')
if [ "${#missing[@]}" -gt 0 ]; then
    run sudo dnf install -y "${missing[@]}" && change "installed ${missing[*]}"
fi

# ------------------------------------------------------------- shell / PATH --
section 'Shell integration'
ensure_dir "$HOME/.bashrc.d"
install_file "$REPO_ROOT/config/rust-dev/bashrc.d/10-rust-dev.sh" \
    "$HOME/.bashrc.d/10-rust-dev.sh" 0644
export PATH="$CARGO_HOME/bin:$HOME/.local/bin${PATH:+:$PATH}"

# -------------------------------------------------------------------- rustup --
# rustup is the toolchain manager, not the toolchain. It installs into the
# isolated container HOME, so no Rust state reaches the host.
section 'rustup'
components=()
for component in ${RUST_COMPONENTS//,/ }; do
    components+=(--component "$component")
done

if [ -x "$CARGO_HOME/bin/rustup" ]; then
    ok "rustup ($("$CARGO_HOME/bin/rustup" --version 2>/dev/null | head -1))"
elif [ "$DRY_RUN" = 1 ]; then
    info "would install rustup into $CARGO_HOME, with toolchain $RUST_VERSION"
else
    curl --proto '=https' --tlsv1.2 -sSf "$RUSTUP_INSTALLER" |
        sh -s -- -y --no-modify-path --profile "$RUST_PROFILE" \
            --default-toolchain "$RUST_VERSION" "${components[@]}" ||
        die 'rustup install failed'
    change "installed rustup with Rust $RUST_VERSION"
fi

# ------------------------------------------------------- baseline toolchain --
# The baseline is what a repository gets when it pins nothing. A repository
# that carries rust-toolchain.toml overrides it, and rustup installs that
# toolchain on first use.
section "Rust $RUST_VERSION baseline toolchain"
if [ "$DRY_RUN" = 1 ]; then
    info "would default to Rust $RUST_VERSION with ${RUST_COMPONENTS//,/ }"
else
    installed=$(rustup toolchain list 2>/dev/null || true)
    case $installed in
        *"$RUST_VERSION"*) ok "toolchain $RUST_VERSION" ;;
        *)
            run rustup toolchain install "$RUST_VERSION" --profile "$RUST_PROFILE" \
                "${components[@]}" && change "installed toolchain $RUST_VERSION"
            ;;
    esac

    current=$(rustup default 2>/dev/null | awk '{print $1}')
    case $current in
        "$RUST_VERSION"*) ok "default toolchain $RUST_VERSION" ;;
        *) run rustup default "$RUST_VERSION" && change "default toolchain $RUST_VERSION" ;;
    esac

    for component in ${RUST_COMPONENTS//,/ }; do
        if rustup component list --toolchain "$RUST_VERSION" 2>/dev/null |
            grep -Eq "^$component[^ ]* \(installed\)"; then
            ok "component $component"
        else
            run rustup component add "$component" --toolchain "$RUST_VERSION" &&
                change "added component $component"
        fi
    done

    rustc_current=$(rustc --version 2>/dev/null | awk '{print $2}')
    [ "$rustc_current" = "$RUST_VERSION" ] ||
        die "rustc reports ${rustc_current:-unknown}; expected $RUST_VERSION"
    ok "rustc $rustc_current"
fi

# The container installs no crate. A dependency belongs to a repository's
# Cargo.toml, and a developer tool belongs to the developer's own cargo install.
section 'Dependency ownership'
ok 'crates remain repository-owned through Cargo.toml'

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
link_into "$LINK_ROOT/bin/sync-agent-skills"        "$HOME/.local/bin/sync-agent-skills"
link_into "$LINK_ROOT/config/rust-dev/bin/orca-ide" "$HOME/.local/bin/orca-ide"
link_into "$LINK_ROOT/config/rust-dev/bin/orca-ide" "$HOME/.local/bin/orca"

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

manual 'Authenticate Claude Code in rust-dev: claude  (then /login)'
manual 'Authenticate Codex in rust-dev: codex login'
manual 'Authenticate GitHub in rust-dev: gh auth login --git-protocol ssh'
manual 'Pin the toolchain of a project with rust-toolchain.toml'
manual 'Verify the environment: ./verify.sh --only 26'

summary
