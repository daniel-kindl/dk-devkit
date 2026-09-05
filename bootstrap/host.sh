#!/usr/bin/env bash
#
# Bootstrap the Bazzite HOST half of the workstation.
#
#   bootstrap/host.sh [--dry-run] [--skip-flatpak] [--skip-brew]
#
# What it does, all idempotently:
#   * creates ~/projects and ~/.local/bin
#   * installs the Homebrew taps, formulae and casks in manifests/homebrew.txt
#   * installs the Flatpak applications in manifests/flatpaks.txt
#   * installs the devbox router, its verification suite and the compatibility
#     wrappers into ~/.local/bin as symlinks into this checkout
#   * generates the claude and codex host shims with 'devbox new-shim'
#   * installs the devbox router configuration into ~/.config/devbox-router
#   * creates the web-dev Distrobox from distrobox/web-dev.ini when it is absent
#   * merges the non-secret Codex preferences into the host ~/.codex/config.toml
#   * installs the agentbox CLI and prepares its credential file location
#
# What it never does:
#   * install a Node or npm toolchain on the host
#   * touch an existing web-dev container
#   * write any credential
#   * overwrite live devbox repository assignments

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=lib/common.sh
. "$REPO_ROOT/bootstrap/lib/common.sh"
# shellcheck source=lib/sandcastle.sh
. "$REPO_ROOT/bootstrap/lib/sandcastle.sh"

SKIP_FLATPAK=0
SKIP_BREW=0
while [ $# -gt 0 ]; do
    case $1 in
        --dry-run) DRY_RUN=1; shift ;;
        --skip-flatpak) SKIP_FLATPAK=1; shift ;;
        --skip-brew) SKIP_BREW=1; shift ;;
        -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
        *) die "unknown option: $1" ;;
    esac
done

if [ -f /run/.containerenv ] || [ -f /.dockerenv ]; then
    die "this is the HOST bootstrap; run it on Bazzite, not inside a container"
fi

printf '%sworkstation host bootstrap%s\n' "$BOLD" "$RESET"
info "checkout   $REPO_ROOT"
info "home       $HOME"
[ "$DRY_RUN" = 1 ] && info "DRY RUN - nothing is written"

# --------------------------------------------------------------- directories --
section 'Directories'
ensure_dir_reported "$HOME/projects"
ensure_dir_reported "$HOME/.local/bin"
ensure_dir_reported "$HOME/.config/devbox-router/environments.d"

# ----------------------------------------------------------------- Homebrew --
section 'Homebrew (host CLI tools)'
BREW=""
for candidate in "$(command -v brew 2>/dev/null || true)" /home/linuxbrew/.linuxbrew/bin/brew; do
    [ -n "$candidate" ] && [ -x "$candidate" ] && { BREW=$candidate; break; }
done
if [ "$SKIP_BREW" = 1 ]; then
    info 'skipped (--skip-brew)'
elif [ -z "$BREW" ]; then
    warn 'Homebrew is not installed'
    manual 'Install Homebrew on Bazzite: run "ujust install-brew", then re-run bootstrap/host.sh'
else
    # Compare on the basename: "brew list --full-name" prints a tapped package
    # as "owner/tap/name", while the manifest may name it either way.
    installed_formula=$("$BREW" list --formula --full-name 2>/dev/null | sed 's|.*/||' || true)
    installed_cask=$("$BREW" list --cask --full-name 2>/dev/null | sed 's|.*/||' || true)
    installed_tap=$("$BREW" tap 2>/dev/null || true)
    while read -r kind name; do
        case ${kind:-} in
            ''|'#'*) continue ;;
        esac
        [ -n "${name:-}" ] || continue
        case $kind in
            tap)
                if printf '%s\n' "$installed_tap" | grep -qxF "$name"; then
                    ok "tap $name"
                else
                    run "$BREW" tap "$name" && change "tap $name"
                fi
                ;;
            trust)
                # 'brew trust' is required before a cask from a third-party tap
                # can be installed. It is safe to repeat.
                run "$BREW" trust "$name" >/dev/null 2>&1 || true
                ok "trust $name"
                ;;
            formula)
                if printf '%s\n' "$installed_formula" | grep -qxF "${name##*/}"; then
                    ok "formula $name"
                else
                    run "$BREW" install "$name" && change "formula $name"
                fi
                ;;
            cask)
                if printf '%s\n' "$installed_cask" | grep -qxF "${name##*/}"; then
                    ok "cask $name"
                else
                    run "$BREW" install --cask "$name" && change "cask $name"
                fi
                ;;
            *) warn "unknown manifest kind '$kind' in manifests/homebrew.txt" ;;
        esac
    done < <(sed -e 's/#.*//' "$REPO_ROOT/manifests/homebrew.txt" | awk 'NF')
fi

# ------------------------------------------------------------------ Flatpak --
section 'Flatpak applications'
if [ "$SKIP_FLATPAK" = 1 ]; then
    info 'skipped (--skip-flatpak)'
elif ! have flatpak; then
    warn 'flatpak is not available'
else
    installed_flatpak=$(flatpak list --app --columns=application 2>/dev/null || true)
    while read -r app; do
        case ${app:-} in ''|'#'*) continue ;; esac
        if printf '%s\n' "$installed_flatpak" | grep -qxF "$app"; then
            ok "$app"
        else
            run flatpak install --or-update --noninteractive --user flathub "$app" &&
                change "$app"
        fi
    done < <(sed -e 's/#.*//' "$REPO_ROOT/manifests/flatpaks.txt" | awk 'NF')
fi

# ------------------------------------------------------------ devbox router --
section 'devbox router (~/.local/bin)'
for tool in devbox devbox-verify devbox-run web-dev-run; do
    link_into "$REPO_ROOT/bin/$tool" "$HOME/.local/bin/$tool"
done

section 'Agent host shims'
# The shims are generated by the router itself, so their content never drifts
# from the router that consumes them. 'devbox new-shim' refuses to overwrite.
for tool in claude codex; do
    if [ -e "$HOME/.local/bin/$tool" ]; then
        ok "$HOME/.local/bin/$tool"
    else
        run "$REPO_ROOT/bin/devbox" new-shim "$tool" && change "$HOME/.local/bin/$tool"
    fi
done

section 'devbox router configuration (~/.config/devbox-router)'
CFG=$HOME/.config/devbox-router
link_into "$REPO_ROOT/config/devbox-router/README.md"                  "$CFG/README.md"
link_into "$REPO_ROOT/config/devbox-router/settings.env"               "$CFG/settings.env"
link_into "$REPO_ROOT/config/devbox-router/inference.tsv"              "$CFG/inference.tsv"
link_into "$REPO_ROOT/config/devbox-router/environments.d/web-dev.env" "$CFG/environments.d/web-dev.env"
# repos.tsv holds absolute host paths. It is machine state: seed it once, then
# leave it to 'devbox assign'.
install_if_absent "$REPO_ROOT/config/devbox-router/repos.tsv.template" "$CFG/repos.tsv"

# ---------------------------------------------------------------- Distrobox --
section 'Distrobox environment: web-dev'
if ! have distrobox; then
    warn 'distrobox is not installed'
    manual 'Install distrobox on the host, then re-run bootstrap/host.sh'
elif podman container exists web-dev 2>/dev/null; then
    ok 'container web-dev already exists (left untouched)'
    info 'to recreate it deliberately, see docs/recovery.md'
else
    run distrobox assemble create --file "$REPO_ROOT/distrobox/web-dev.ini" &&
        change 'created container web-dev'
fi

# ------------------------------------------------------- Codex host settings --
section 'Codex host preferences (~/.codex/config.toml)'
# Orca points CODEX_HOME at a HOST path that is bind-mounted into the box, so
# the host ~/.codex is a real Codex home and needs the shared preferences too.
ensure_dir "$HOME/.codex"
if [ "$DRY_RUN" = 1 ]; then
    info "would merge $REPO_ROOT/config/codex/config.base.toml into $HOME/.codex/config.toml"
else
    python3 "$REPO_ROOT/bin/merge-toml-defaults.py" \
        "$HOME/.codex/config.toml" "$REPO_ROOT/config/codex/config.base.toml"
fi

section 'Codex host policy and status line'
# Codex reads its global instructions from $CODEX_HOME/AGENTS.md. The host
# Codex home therefore needs the same shared policy file as the one inside the
# container, and the same status line item list.
link_into "$REPO_ROOT/config/agents/AGENTS.md" "$HOME/.codex/AGENTS.md"
if [ "$DRY_RUN" = 1 ]; then
    info 'would apply the shared status line to the host Codex home'
else
    SPEC_DIR="$REPO_ROOT/config/agents/statusline" \
    CODEX_CONFIG="$HOME/.codex/config.toml" \
    AGENT_BACKUP_DIR="$(backup_dir)" \
        "$REPO_ROOT/config/agents/statusline/install.sh" --codex-only |
        sed 's/^/  /'
fi

# --------------------------------------------------- Sandcastle (agentbox) --
section 'Agent orchestration (agentbox)'
install_agentbox "$REPO_ROOT"
# An image build needs the network and takes minutes, so it stays an explicit
# command. Report whether it has been done.
if have podman; then
    # The subshell keeps the manifest variables out of this script, and sits in
    # a condition so that a missing image does not trip "set -e".
    # shellcheck source=/dev/null
    if ( . "$REPO_ROOT/manifests/sandcastle.env"
         podman image exists "$RUNNER_IMAGE:$RUNNER_TAG" ) 2>/dev/null; then
        ok 'the agentbox images are built'
    else
        info 'the agentbox images are not built yet'
        manual 'Build the agent sandbox images: agentbox build'
    fi
else
    warn 'podman is not available; agentbox cannot run'
fi

# ---------------------------------------------------------------------- Orca --
section 'Orca'
if [ -x "$HOME/.local/bin/orca-ide" ]; then
    ok "$HOME/.local/bin/orca-ide"
else
    warn 'orca-ide is not registered on the host'
    manual 'Install the Orca desktop app, open it once, and let it register its CLI as ~/.local/bin/orca-ide (named orca-ide on Linux so it does not collide with the GNOME Orca screen reader)'
fi

# ------------------------------------------------------------ manual reminders --
manual 'Restore the SSH key (see docs/secrets.md), then: ssh-add ~/.ssh/id_ed25519'
manual 'Authenticate GitHub on the host: gh auth login --git-protocol ssh'
manual 'Mint an unattended Claude token on the host with "claude setup-token", then put it in ~/.config/agentbox/secrets.env'
manual 'Run bootstrap/web-dev.sh inside the container: devbox exec web-dev --cwd ~/projects/workstation -- ./bootstrap/web-dev.sh'

summary
