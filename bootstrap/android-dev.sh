#!/usr/bin/env bash
#
# Bootstrap the reusable android-dev Distrobox.
# Run this inside android-dev through devbox.

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=lib/common.sh
. "$REPO_ROOT/bootstrap/lib/common.sh"

while [ $# -gt 0 ]; do
    case $1 in
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
        *) die "unknown option: $1" ;;
    esac
done

if [ ! -f /run/.containerenv ] && [ ! -f /.dockerenv ]; then
    die 'this bootstrap must run inside the android-dev container, not on the host'
fi

# shellcheck source=../manifests/android-dev.env
. "$REPO_ROOT/manifests/android-dev.env"
# shellcheck source=../manifests/toolchain.env
. "$REPO_ROOT/manifests/toolchain.env"

SDK_ROOT=$HOME/$ANDROID_SDK_ROOT_REL
TOOLS_DIR=$SDK_ROOT/cmdline-tools/latest

printf '%sworkstation android-dev bootstrap%s\n' "$BOLD" "$RESET"
info "checkout   $REPO_ROOT"
info "box home   $HOME"
info "SDK        $SDK_ROOT"
[ "$DRY_RUN" = 1 ] && info 'DRY RUN - nothing is written'

section 'Distribution packages'
missing=()
while read -r pkg; do
    case ${pkg:-} in ''|'#'*) continue ;; esac
    rpm -q "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
done < <(sed -e 's/#.*//' "$REPO_ROOT/manifests/android-dev-packages.txt" | awk 'NF')
[ "${#missing[@]}" -eq 0 ] || run sudo dnf install -y "${missing[@]}"

section 'Shell integration'
ensure_dir "$HOME/.bashrc.d"
install_file "$REPO_ROOT/config/android-dev/bashrc.d/10-android-dev.sh" \
    "$HOME/.bashrc.d/10-android-dev.sh" 0644
export JAVA_HOME="$JAVA_HOME_REL"
export ANDROID_SDK_ROOT="$SDK_ROOT"
export ANDROID_HOME="$SDK_ROOT"
export PATH="$TOOLS_DIR/bin:$SDK_ROOT/platform-tools:$SDK_ROOT/emulator:$PATH"

section 'Android command-line tools'
if [ -x "$TOOLS_DIR/bin/sdkmanager" ] && [ -f "$TOOLS_DIR/.version" ] &&
   [ "$(cat "$TOOLS_DIR/.version")" = "$ANDROID_CMDLINE_TOOLS_VERSION" ]; then
    ok "Android command-line tools $ANDROID_CMDLINE_TOOLS_VERSION"
elif [ "$DRY_RUN" = 1 ]; then
    info "would install Android command-line tools $ANDROID_CMDLINE_TOOLS_VERSION"
else
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    curl -fsSL "https://dl.google.com/android/repository/commandlinetools-linux-${ANDROID_CMDLINE_TOOLS_VERSION}_latest.zip" \
        -o "$tmp/tools.zip"
    ensure_dir "$SDK_ROOT"
    rm -rf "$tmp/tools" "$SDK_ROOT/cmdline-tools.new"
    unzip -q "$tmp/tools.zip" -d "$tmp"
    mv "$tmp/cmdline-tools" "$SDK_ROOT/cmdline-tools.new"
    rm -rf "$TOOLS_DIR"
    ensure_dir "$SDK_ROOT/cmdline-tools"
    mv "$SDK_ROOT/cmdline-tools.new" "$TOOLS_DIR"
    printf '%s\n' "$ANDROID_CMDLINE_TOOLS_VERSION" > "$TOOLS_DIR/.version"
    change "installed Android command-line tools $ANDROID_CMDLINE_TOOLS_VERSION"
fi

section 'Android SDK packages'
if [ -x "$TOOLS_DIR/bin/sdkmanager" ]; then
    sdk_packages=(${ANDROID_PACKAGES})
    run mkdir -p "$SDK_ROOT"
    if [ "$DRY_RUN" = 1 ]; then
        info "would accept Android SDK licenses and install: ${sdk_packages[*]}"
    else
        # sdkmanager closes stdin after it accepts all licenses. Disable
        # pipefail for this pipeline so yes receiving SIGPIPE is not an error.
        set +o pipefail
        yes | "$TOOLS_DIR/bin/sdkmanager" --sdk_root="$SDK_ROOT" --licenses >/dev/null
        set -o pipefail
        "$TOOLS_DIR/bin/sdkmanager" --sdk_root="$SDK_ROOT" "${sdk_packages[@]}"
        change "installed Android SDK packages: ${sdk_packages[*]}"
    fi
else
    warn 'Android SDK packages skipped because sdkmanager is not installed'
fi

section 'Shared agent configuration'
ensure_dir "$HOME/.agents/skills"
LINK_ROOT=$REPO_ROOT
if [ -n "${DISTROBOX_HOST_HOME:-}" ]; then
    candidate=${REPO_ROOT/#\/workspace/$DISTROBOX_HOST_HOME/projects}
    if [ "$candidate" != "$REPO_ROOT" ] && [ -e "$candidate" ] && [ "$candidate" -ef "$REPO_ROOT" ]; then
        LINK_ROOT=$candidate
    fi
fi
link_into "$LINK_ROOT/config/agents/AGENTS.md" "$HOME/.agents/AGENTS.md"
link_into "$LINK_ROOT/config/agents/statusline" "$HOME/.agents/statusline"
ensure_dir "$HOME/.claude"
ensure_dir "$HOME/.codex"
link_into "$HOME/.agents/AGENTS.md" "$HOME/.claude/CLAUDE.md"
link_into "$HOME/.agents/AGENTS.md" "$HOME/.codex/AGENTS.md"
link_into "$HOME/.agents/skills" "$HOME/.claude/skills"
ensure_dir "$HOME/.local/bin"
link_into "$LINK_ROOT/bin/sync-agent-skills" "$HOME/.local/bin/sync-agent-skills"

section 'Agent CLIs'
if [ -x "$HOME/.local/bin/claude" ]; then ok 'claude is installed'; else run bash -c "curl -fsSL $CLAUDE_CODE_INSTALLER | bash"; fi
if [ -x "$HOME/.local/bin/codex" ]; then ok 'codex is installed'; else run bash -c "curl -fsSL $CODEX_INSTALLER | sh"; fi

manual 'Authenticate Claude Code in android-dev: claude (then /login)'
manual 'Authenticate Codex in android-dev: codex login'
manual 'Run the Ocho checks from its checkout: ./gradlew check'
manual 'Use a host emulator or a connected device for connected Android tests'
summary
