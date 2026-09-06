#!/usr/bin/env bash
#
# Bootstrap the Bazzite HOST half of the workstation.
#
#   bootstrap/host.sh [--dry-run] [--skip-flatpak] [--skip-brew]
#
# This is the complete host composition. It is the `daniel` profile expressed
# as one script, and it stays supported while the component installer in
# install.sh takes over piece by piece. Each step below is one toolkit
# component, and both entry points call the same library function.
#
# What it does, all idempotently:
#   * creates ~/projects and ~/.local/bin
#   * installs the Homebrew taps, formulae and casks in manifests/homebrew.txt
#   * installs the Flatpak applications in manifests/flatpaks.txt
#   * installs the devbox router, its verification suite and the compatibility
#     wrappers into ~/.local/bin as symlinks into this checkout
#   * generates the claude and codex host shims with 'devbox new-shim'
#   * installs the devbox router configuration into ~/.config/devbox-router
#   * creates the Distrobox of every supported environment module
#   * merges the non-secret Codex preferences into the host ~/.codex/config.toml
#   * installs the agentbox CLI and prepares its credential file location
#   * installs the agentq host shim, which delegates into the container
#   * installs Pi once on the host, with its own private Node runtime
#
# What it never does:
#   * install a Node, npm, Python, or uv toolchain on the host: the private
#     runtime that Pi needs is reachable from Pi only, never from a host shell
#   * install the agentq runtime on the host: the host gets the shim only
#   * touch an existing development container
#   * write any credential
#   * overwrite live devbox repository assignments

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=lib/common.sh
. "$REPO_ROOT/bootstrap/lib/common.sh"
# shellcheck source=lib/platform.sh
. "$REPO_ROOT/bootstrap/lib/platform.sh"
# shellcheck source=lib/host-packages.sh
. "$REPO_ROOT/bootstrap/lib/host-packages.sh"
# shellcheck source=lib/devbox.sh
. "$REPO_ROOT/bootstrap/lib/devbox.sh"
# shellcheck source=lib/environments.sh
. "$REPO_ROOT/bootstrap/lib/environments.sh"
# shellcheck source=lib/agent-home.sh
. "$REPO_ROOT/bootstrap/lib/agent-home.sh"
# shellcheck source=lib/pi.sh
. "$REPO_ROOT/bootstrap/lib/pi.sh"
# shellcheck source=lib/sandcastle.sh
. "$REPO_ROOT/bootstrap/lib/sandcastle.sh"
# shellcheck source=lib/agentq.sh
. "$REPO_ROOT/bootstrap/lib/agentq.sh"

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

# ----------------------------------------------------------------- Homebrew --
section 'Homebrew (host CLI tools)'
if [ "$SKIP_BREW" = 1 ]; then
    info 'skipped (--skip-brew)'
else
    install_homebrew_packages "$REPO_ROOT"
fi

# ------------------------------------------------------------------ Flatpak --
section 'Flatpak applications'
if [ "$SKIP_FLATPAK" = 1 ]; then
    info 'skipped (--skip-flatpak)'
else
    install_flatpak_apps "$REPO_ROOT"
fi

# ------------------------------------------------------------ devbox router --
install_devbox_router "$REPO_ROOT"

# ---------------------------------------------------------------- Distrobox --
section 'Distrobox development environments'
# The environment modules under components/ say which environments exist. This
# script names none of them, so a new environment is one new module.
create_development_environments "$REPO_ROOT"
info 'to recreate a development container deliberately, see docs/recovery.md'

# ------------------------------------------------------- Codex host settings --
install_host_agent_home "$REPO_ROOT"

# ------------------------------------------------------------------------ Pi --
# Pi is the one interactive agent that runs ON the host. It is installed once,
# with its own private Node runtime, so the host rule against a Node toolchain
# still holds. It is not installed into any development environment, and
# ~/.local/bin/pi is not a router shim. See docs/architecture.md.
install_host_pi "$REPO_ROOT"

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

# ------------------------------------------- the GitHub backlog coordinator --
section 'GitHub backlog coordinator host entry point (agentq)'
# The coordinator itself stays inside the container: it needs gh and the
# forwarded ssh-agent, and the host keeps no Node toolchain. The host gets the
# COMMAND, as a router shim that carries the working directory across and holds
# no credential of its own. See docs/agentq.md.
install_agentq_host_shim "$REPO_ROOT"

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

summary
