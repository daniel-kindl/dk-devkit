# Bazzite host: required commands, directories and package managers.
#
# The container runtime lives in module 1e, and the desktop applications in
# module 1f, because each of them is one component's own verification.

section '1. Bazzite host'

if [ "$IN_CONTAINER" = 1 ]; then
    check 'host is reachable from the container (distrobox-host-exec)' \
        -- on_host true
fi

for cmd in git flatpak; do
    if host_sh "command -v $cmd" >/dev/null 2>&1; then
        pass "host command: $cmd"
    else
        fail "host command: $cmd" "not found on the Bazzite host"
    fi
done

# Homebrew is not on the default PATH of a non-interactive host shell.
if host_sh 'test -x /home/linuxbrew/.linuxbrew/bin/brew || command -v brew' >/dev/null 2>&1; then
    pass 'host command: brew'
else
    fail 'host command: brew' 'Homebrew is not installed (ujust install-brew)'
fi

check 'host: ~/projects exists' -- on_host test -d "$HOST_HOME/projects"
check 'host: ~/.local/bin exists' -- on_host test -d "$HOST_HOME/.local/bin"

# Node must NOT be installed on the host: toolchains belong inside a Distrobox.
if host_sh 'command -v node || command -v npm' >/dev/null 2>&1; then
    fail 'host has no Node toolchain' \
         "found: $(host_sh 'command -v node; command -v npm' 2>/dev/null | tr '\n' ' ')" \
         'Development toolchains belong inside the appropriate Distrobox.'
else
    pass 'host has no Node toolchain (correct: toolchains live in the box)'
fi

section '1b. Host package manifests'

brew_bin=$(host_sh 'command -v brew || printf /home/linuxbrew/.linuxbrew/bin/brew' 2>/dev/null)
if on_host test -x "$brew_bin" 2>/dev/null; then
    # Compare on the basename: --full-name prints "owner/tap/name".
    brew_have=$(host_sh "$brew_bin list --formula --full-name 2>/dev/null; $brew_bin list --cask --full-name 2>/dev/null" |
                sed 's|.*/||' || true)
    missing=''
    while read -r kind name; do
        case ${kind:-} in ''|'#'*) continue ;; esac
        case $kind in formula|cask) ;; *) continue ;; esac
        printf '%s\n' "$brew_have" | grep -qxF "${name##*/}" && continue
        missing="$missing $name"
    done < <(sed -e 's/#.*//' "$REPO_ROOT/manifests/homebrew.txt" | awk 'NF')
    if [ -z "$missing" ]; then
        pass 'every Homebrew package in manifests/homebrew.txt is installed'
    else
        fail 'Homebrew manifest is satisfied' "missing:$missing" 'run bootstrap/host.sh'
    fi
else
    skip 'Homebrew manifest' 'brew not installed'
fi
