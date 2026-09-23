#!/usr/bin/env bash
#
# Bootstrap the reusable godot-dev Distrobox.
# Run this inside godot-dev through devbox.

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=lib/common.sh
. "$REPO_ROOT/bootstrap/lib/common.sh"
# shellcheck source=lib/agents.sh
. "$REPO_ROOT/bootstrap/lib/agents.sh"
# shellcheck source=lib/dotnet.sh
. "$REPO_ROOT/bootstrap/lib/dotnet.sh"

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
    die 'this bootstrap must run inside the godot-dev container, not on the host'
fi

# shellcheck source=../manifests/godot-dev.env
. "$REPO_ROOT/manifests/godot-dev.env"
# shellcheck source=../manifests/toolchain.env
. "$REPO_ROOT/manifests/toolchain.env"
# shellcheck source=../manifests/dotnet-sdk.env
. "$REPO_ROOT/manifests/dotnet-sdk.env"

export DOTNET_CLI_HOME="$HOME/$DOTNET_CLI_HOME_REL"
DOTNET_SDK_ROOT=$HOME/$DOTNET_SDK_ROOT_REL
export DOTNET_ROOT="$DOTNET_SDK_ROOT"
export PATH="$DOTNET_SDK_ROOT:$HOME/.local/bin${PATH:+:$PATH}"

# One release names three things: the archive, the directory inside it, and the
# binary. The binary spells the architecture with a dot where the directory
# spells it with an underscore.
GODOT_TAG=$GODOT_VERSION-$GODOT_RELEASE
GODOT_STEM=Godot_v${GODOT_TAG}_${GODOT_FLAVOR}_linux_x86_64
GODOT_BINARY_NAME=Godot_v${GODOT_TAG}_${GODOT_FLAVOR}_linux.x86_64
GODOT_URL=https://github.com/godotengine/godot/releases/download/$GODOT_TAG/$GODOT_STEM.zip
GODOT_DIR=$HOME/$GODOT_ROOT_REL/$GODOT_TAG-$GODOT_FLAVOR
GODOT_BINARY=$GODOT_DIR/$GODOT_BINARY_NAME
GODOT_COMMAND=$HOME/.local/bin/godot
DESKTOP_FILE=$HOME/.local/share/applications/godot.desktop

LINK_ROOT=$REPO_ROOT
if [ -n "${DISTROBOX_HOST_HOME:-}" ]; then
    candidate=${REPO_ROOT/#\/workspace/$DISTROBOX_HOST_HOME/projects}
    if [ "$candidate" != "$REPO_ROOT" ] && [ -e "$candidate" ] && [ "$candidate" -ef "$REPO_ROOT" ]; then
        LINK_ROOT=$candidate
    fi
fi

printf '%sdk-devkit godot-dev bootstrap%s\n' "$BOLD" "$RESET"
info "checkout   $REPO_ROOT"
info "link root  $LINK_ROOT"
info "box home   $HOME"
info "engine     $GODOT_DIR"
info "DOTNET_CLI_HOME $DOTNET_CLI_HOME"
info "DOTNET_ROOT $DOTNET_ROOT"
[ "$DRY_RUN" = 1 ] && info 'DRY RUN - nothing is written'

section 'Distribution packages'
missing=()
while read -r pkg; do
    [ -n "${pkg:-}" ] || continue
    rpm -q "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
done < <(sed -e 's/#.*//' "$REPO_ROOT/manifests/godot-dev-packages.txt" | awk 'NF')
[ "${#missing[@]}" -eq 0 ] || run sudo dnf install -y "${missing[@]}"

section 'Shell integration'
ensure_dir "$HOME/.bashrc.d"
install_file "$REPO_ROOT/config/godot-dev/bashrc.d/10-godot-dev.sh" \
    "$HOME/.bashrc.d/10-godot-dev.sh" 0644

section '.NET SDK'
# The distribution package is feature band 1xx only. A repository pins a band
# in global.json, and no rollForward policy moves down a band, so the
# environment installs the pinned upstream SDK and puts it in front.
# manifests/dotnet-sdk.env says why.
ensure_dotnet_sdk "$DOTNET_SDK_ROOT" "$DOTNET_SDK_VERSION" "$DOTNET_SDK_SHA512"
if [ -x "$DOTNET_SDK_ROOT/dotnet" ]; then
    ok "dotnet resolves to $(command -v dotnet)"
elif [ "$DRY_RUN" != 1 ]; then
    die "the pinned .NET SDK is missing: $DOTNET_SDK_ROOT/dotnet"
fi

section 'Godot engine'
# The distribution package is the standard build, which cannot run C#. This is
# the upstream .NET build, checked against the digest the manifest pins.
if [ -x "$GODOT_BINARY" ]; then
    ok "godot $($GODOT_BINARY --headless --version 2>/dev/null | head -1)"
elif [ "$DRY_RUN" = 1 ]; then
    info "would install Godot $GODOT_TAG ($GODOT_FLAVOR) from $GODOT_URL"
else
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    curl -fsSL "$GODOT_URL" -o "$tmp/godot.zip"
    printf '%s  %s\n' "$GODOT_SHA512" "$tmp/godot.zip" | sha512sum -c - >/dev/null ||
        die "the Godot download does not match GODOT_SHA512 in manifests/godot-dev.env"
    unzip -q "$tmp/godot.zip" -d "$tmp"
    [ -d "$tmp/$GODOT_STEM" ] || die "the archive does not contain $GODOT_STEM"
    ensure_dir "$(dirname -- "$GODOT_DIR")"
    rm -rf -- "$GODOT_DIR"
    mv -- "$tmp/$GODOT_STEM" "$GODOT_DIR"
    chmod +x "$GODOT_BINARY"
    change "installed Godot $GODOT_TAG ($GODOT_FLAVOR)"
    rm -rf "$tmp"
    trap - EXIT
fi

section 'Godot command and desktop entry'
ensure_dir "$HOME/.local/bin"
# The command is a launcher, not a symlink. The editor builds C#, so it needs
# the pinned SDK in front of the distribution package, and the host
# application menu cannot get that from ~/.bashrc.d: distrobox-enter runs the
# entry WITHOUT a login shell. config/godot-dev/bin/godot says the same.
if [ ! -x "$GODOT_BINARY" ] && [ "$DRY_RUN" != 1 ]; then
    die "the Godot binary is missing: $GODOT_BINARY"
fi
# An earlier version linked this name straight at the engine. Remove such a
# link first: install_file copies onto the destination, and a copy onto a
# symlink writes through it and would overwrite the engine binary.
if [ -L "$GODOT_COMMAND" ]; then
    save_copy "$GODOT_COMMAND"
    run rm -f -- "$GODOT_COMMAND"
fi
rendered=$(mktemp) || die 'cannot create a temporary file'
sed -e "s|@DOTNET_ROOT@|$DOTNET_SDK_ROOT|" \
    -e "s|@DOTNET_CLI_HOME@|$DOTNET_CLI_HOME|" \
    -e "s|@GODOT_BINARY@|$GODOT_BINARY|" \
    -- "$REPO_ROOT/config/godot-dev/bin/godot" > "$rendered"
install_file "$rendered" "$GODOT_COMMAND" 0755
rm -f -- "$rendered"
ensure_dir "$HOME/.local/share/applications"
# The entry names the engine by absolute path. distrobox-enter runs a command
# WITHOUT a login shell, and the PATH it passes is the host one, which does not
# hold this container's ~/.local/bin, so a bare name does not resolve.
rendered=$(mktemp) || die 'cannot create a temporary file'
sed -e "s|@GODOT_COMMAND@|$GODOT_COMMAND|" \
    -- "$REPO_ROOT/config/godot-dev/godot.desktop" > "$rendered"
desktop_changed=1
if [ -f "$DESKTOP_FILE" ] && cmp -s -- "$rendered" "$DESKTOP_FILE"; then
    desktop_changed=0
fi
install_file "$rendered" "$DESKTOP_FILE" 0644
rm -f -- "$rendered"

# The editor is a window, so the host application menu gets an entry for it.
# distrobox-export writes into the host HOME through the container.
if [ "$DRY_RUN" = 1 ]; then
    info "would export $DESKTOP_FILE to the host application menu"
elif ! have distrobox-export; then
    warn 'distrobox-export is not available; the editor stays a command inside the box'
elif [ "$desktop_changed" = 0 ] &&
     distrobox-export --list-apps 2>/dev/null | grep -q 'godot\.desktop'; then
    ok 'the host application menu has the Godot entry'
else
    # An existing export keeps the old command line, so replace it.
    distrobox-export --app "$DESKTOP_FILE" --delete >/dev/null 2>&1 || true
    run distrobox-export --app "$DESKTOP_FILE" && change 'exported Godot to the host application menu'
fi

install_agent_clis

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
link_into "$LINK_ROOT/bin/sync-agent-skills" "$HOME/.local/bin/sync-agent-skills"
link_into "$LINK_ROOT/config/godot-dev/bin/orca-ide" "$HOME/.local/bin/orca-ide"
link_into "$LINK_ROOT/config/godot-dev/bin/orca-ide" "$HOME/.local/bin/orca"

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
    "$HOME/.agents/statusline/install.sh"
fi

manual 'Authenticate Claude Code in godot-dev: claude (then /login)'
manual 'Authenticate Codex in godot-dev: codex login'
manual 'Authenticate Grok in godot-dev: grok (the first start opens a browser)'
manual 'Authenticate GitHub in godot-dev: gh auth login --git-protocol ssh --skip-ssh-key'
manual 'Install the export templates before the first export; docs/godot-dev.md gives the command'
manual 'Verify the environment: ./verify.sh --only 21'
summary
