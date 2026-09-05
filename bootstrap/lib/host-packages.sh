# Host package installation from the tracked manifests.
# Source this file; do not execute it. It needs bootstrap/lib/common.sh.
#
# Homebrew supplies the host CLI tools and Flatpak supplies the desktop
# applications. Both are personal-workstation package sets, so each one is a
# separate function and a separate toolkit component.

# install_homebrew_packages <repo-root>
#
# Converges the taps, formulae and casks in manifests/homebrew.txt. It reports
# a missing Homebrew as a manual step rather than installing Homebrew itself.
install_homebrew_packages() {
    local repo_root=$1
    local brew='' candidate
    local installed_formula installed_cask installed_tap kind name

    for candidate in "$(command -v brew 2>/dev/null || true)" \
                     /home/linuxbrew/.linuxbrew/bin/brew; do
        [ -n "$candidate" ] && [ -x "$candidate" ] && { brew=$candidate; break; }
    done
    if [ -z "$brew" ]; then
        warn 'Homebrew is not installed'
        manual 'Install Homebrew on Bazzite: run "ujust install-brew", then re-run the installer'
        return 0
    fi

    # Compare on the basename: "brew list --full-name" prints a tapped package
    # as "owner/tap/name", while the manifest may name it either way.
    installed_formula=$("$brew" list --formula --full-name 2>/dev/null | sed 's|.*/||' || true)
    installed_cask=$("$brew" list --cask --full-name 2>/dev/null | sed 's|.*/||' || true)
    installed_tap=$("$brew" tap 2>/dev/null || true)
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
                    run "$brew" tap "$name" && change "tap $name"
                fi
                ;;
            trust)
                # 'brew trust' is required before a cask from a third-party tap
                # can be installed. It is safe to repeat.
                run "$brew" trust "$name" >/dev/null 2>&1 || true
                ok "trust $name"
                ;;
            formula)
                if printf '%s\n' "$installed_formula" | grep -qxF "${name##*/}"; then
                    ok "formula $name"
                else
                    run "$brew" install "$name" && change "formula $name"
                fi
                ;;
            cask)
                if printf '%s\n' "$installed_cask" | grep -qxF "${name##*/}"; then
                    ok "cask $name"
                else
                    run "$brew" install --cask "$name" && change "cask $name"
                fi
                ;;
            *) warn "unknown manifest kind '$kind' in manifests/homebrew.txt" ;;
        esac
    done < <(sed -e 's/#.*//' "$repo_root/manifests/homebrew.txt" | awk 'NF')
}

# install_flatpak_apps <repo-root>
#
# Converges the user Flatpak applications in manifests/flatpaks.txt.
install_flatpak_apps() {
    local repo_root=$1
    local installed_flatpak app

    if ! have flatpak; then
        warn 'flatpak is not available'
        return 0
    fi
    installed_flatpak=$(flatpak list --app --columns=application 2>/dev/null || true)
    while read -r app; do
        case ${app:-} in ''|'#'*) continue ;; esac
        if printf '%s\n' "$installed_flatpak" | grep -qxF "$app"; then
            ok "$app"
        else
            run flatpak install --or-update --noninteractive --user flathub "$app" &&
                change "$app"
        fi
    done < <(sed -e 's/#.*//' "$repo_root/manifests/flatpaks.txt" | awk 'NF')
}
