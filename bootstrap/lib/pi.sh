# The host Pi installation.
# Source this file; do not execute it. It needs bootstrap/lib/common.sh.
#
# Pi is a HOST control-plane tool, and there is exactly one installation of it.
# It is deliberately NOT installed into a development environment, and
# ~/.local/bin/pi is deliberately NOT a devbox router shim: the existing claude
# and codex shims route into the environment that owns a repository because
# those CLIs live inside that environment, and Pi does not. Delegating a
# project command from Pi into a development environment is separate future
# work, and it will call the existing devbox router rather than repeat it.
#
# Pi needs Node. The host must not gain a Node development toolchain, so this
# installs Pi's own PRIVATE runtime, in the location and the layout that the
# official pi.dev installer uses for a standalone Node. It is not on the host
# PATH. Only the generated launcher puts it on the PATH of the Pi process.
#
# manifests/pi.env holds every version and every location.

# pi_manifest <repo-root> - read manifests/pi.env into this shell.
pi_manifest() {
    local repo_root=$1
    # shellcheck source=/dev/null
    . "$repo_root/manifests/pi.env"

    PI_RUNTIME_DIR=$HOME/$PI_RUNTIME_DIR_REL
    PI_RUNTIME_CURRENT=$PI_RUNTIME_DIR/current
    PI_RUNTIME_BIN=$PI_RUNTIME_CURRENT/bin
    PI_PREFIX=$HOME/$PI_PREFIX_REL
    PI_LAUNCHER=$HOME/$PI_LAUNCHER_REL
    PI_AGENT_DIR=$HOME/$PI_AGENT_DIR_REL
    PI_ENTRY=$PI_PREFIX/bin/pi
}

# pi_node_is_new_enough <node-binary> - true when it satisfies PI_NODE_MIN_VERSION.
pi_node_is_new_enough() {
    local node=$1
    [ -x "$node" ] || return 1
    "$node" -e '
        const want = process.argv[1].split(".").map(Number);
        const have = process.versions.node.split(".").map(Number);
        for (let i = 0; i < 3; i += 1) {
            if (have[i] > want[i]) process.exit(0);
            if (have[i] < want[i]) process.exit(1);
        }
        process.exit(0);
    ' "$PI_NODE_MIN_VERSION" >/dev/null 2>&1
}

# pi_host_arch - the Node distribution architecture name for this machine.
pi_host_arch() {
    case $(uname -m) in
        x86_64|amd64)   printf 'x64' ;;
        arm64|aarch64)  printf 'arm64' ;;
        armv7l)         printf 'armv7l' ;;
        ppc64le)        printf 'ppc64le' ;;
        s390x)          printf 's390x' ;;
        *) return 1 ;;
    esac
}

# install_pi_runtime - converge the private Node runtime.
#
# It downloads nothing when a runtime that is new enough is already in place,
# so a second run makes no network call. The archive is verified against the
# checksum file that the distribution publishes beside it, exactly as the
# official Pi installer does.
install_pi_runtime() {
    local arch archive listing staging url

    section 'Pi private Node runtime'
    if pi_node_is_new_enough "$PI_RUNTIME_BIN/node"; then
        ok "$(pretty_home "$PI_RUNTIME_CURRENT") ($("$PI_RUNTIME_BIN/node" --version))"
        return 0
    fi

    arch=$(pi_host_arch) || die "no Node distribution for this CPU: $(uname -m)"
    for tool in curl tar xz; do
        have "$tool" || die "$tool is required to install the Pi runtime"
    done

    if [ "$DRY_RUN" = 1 ]; then
        info "would install Node $PI_NODE_CHANNEL ($arch) into $(pretty_home "$PI_RUNTIME_DIR")"
        change "$(pretty_home "$PI_RUNTIME_CURRENT")"
        return 0
    fi

    url=$PI_NODE_DIST_BASE/$PI_NODE_CHANNEL
    # A fatal error exits the process, so the staging directory is removed by an
    # EXIT trap rather than at the end of this function.
    PI_STAGING=$(mktemp -d "${TMPDIR:-/tmp}/pi-runtime.XXXXXX")
    staging=$PI_STAGING
    trap 'rm -rf -- "${PI_STAGING:-}"' EXIT

    curl -fsSL "$url/SHASUMS256.txt" -o "$staging/SHASUMS256.txt" ||
        die "cannot reach the Node distribution at $url"
    listing=$(awk -v suffix="-linux-$arch.tar.xz" \
        'index($2, "node-v") == 1 && $2 ~ suffix"$" { print $2; exit }' \
        "$staging/SHASUMS256.txt")
    [ -n "$listing" ] || die "no Node build for linux-$arch in $PI_NODE_CHANNEL"

    info "downloading ${listing%.tar.xz}"
    curl -fsSL "$url/$listing" -o "$staging/$listing" || die "cannot download $listing"
    archive=$staging/$listing
    ( cd "$staging" && awk -v f="$listing" '$2 == f' SHASUMS256.txt > selected.txt &&
      sha256sum -c selected.txt >/dev/null ) || die "the Node download failed its checksum"

    ensure_dir "$PI_RUNTIME_DIR"
    rm -rf -- "$PI_RUNTIME_DIR/${listing%.tar.xz}"
    tar -xf "$archive" -C "$PI_RUNTIME_DIR" || die "cannot extract $listing"
    ln -sfn -- "$PI_RUNTIME_DIR/${listing%.tar.xz}" "$PI_RUNTIME_CURRENT"
    change "$(pretty_home "$PI_RUNTIME_CURRENT") -> ${listing%.tar.xz}"
    rm -rf -- "$PI_STAGING"
    PI_STAGING=''
}

# install_pi_package - converge the Pi package inside its own npm prefix.
#
# The prefix belongs to Pi alone. Nothing else is installed into it, and it is
# never added to the host PATH, so the host gains no npm global area.
install_pi_package() {
    section 'Pi package'
    if [ -x "$PI_ENTRY" ]; then
        ok "$(pretty_home "$PI_ENTRY")"
        return 0
    fi
    if [ "$DRY_RUN" = 1 ]; then
        info "would install $PI_PACKAGE into $(pretty_home "$PI_PREFIX")"
        change "$(pretty_home "$PI_ENTRY")"
        return 0
    fi

    [ -x "$PI_RUNTIME_BIN/npm" ] || die "the Pi runtime has no npm; install the runtime first"
    ensure_dir "$PI_PREFIX"
    # --ignore-scripts is what the Pi documentation asks for: Pi needs no
    # dependency lifecycle script, so none is run.
    PATH="$PI_RUNTIME_BIN:$PATH" npm install --global --ignore-scripts \
        --prefix "$PI_PREFIX" --no-fund --no-audit --loglevel=error "$PI_PACKAGE" ||
        die "npm could not install $PI_PACKAGE"
    [ -x "$PI_ENTRY" ] || die "npm installed nothing at $PI_ENTRY"
    change "$(pretty_home "$PI_ENTRY")"
}

# install_pi_launcher <repo-root> - write the host "pi" command.
#
# The launcher is generated, so this repository tracks the generator and not
# the result. docs/not-tracked.md records that.
install_pi_launcher() {
    local repo_root=$1 staging
    section 'Pi host command'
    staging=$(mktemp "${TMPDIR:-/tmp}/pi-launcher.XXXXXX")
    pi_launcher_text > "$staging"
    install_file "$staging" "$PI_LAUNCHER" 0755
    rm -f -- "$staging"
}

# pi_launcher_text - the text of ~/.local/bin/pi.
pi_launcher_text() {
    cat <<EOF
#!/usr/bin/env bash
#
# Pi, on the host. GENERATED by the dk-devkit pi component; do not edit.
# Re-generate it with: ./install.sh --components pi
#
# This is NOT a devbox router shim. Pi is installed once, on the host, and it
# runs there. It is not routed into a development environment, and it is not
# installed into one. Delegating a project command into the environment that
# owns a repository is separate future work, and it will call devbox.
#
# The PATH line below exposes Pi's PRIVATE Node runtime to the Pi process only.
# It is not exported into any interactive host shell, so the host still has no
# Node development toolchain. Pi needs it because Pi runs npm itself when it
# installs or updates a pi package.
set -euo pipefail

# Distrobox forwards the host PATH verbatim, so this command is visible from
# inside a development environment even though it belongs to the host. Refuse
# there. Pi is not installed per environment, and running it from inside one
# would resolve every path against the isolated container HOME.
if [ -f /run/.containerenv ] || [ -f /.dockerenv ]; then
    printf 'pi: refusing to run inside a container.\n' >&2
    printf '  Pi is a host tool and there is exactly one installation.\n' >&2
    printf '  Run it from a host terminal.\n' >&2
    exit 8
fi

PI_RUNTIME_BIN=\$HOME/$PI_RUNTIME_DIR_REL/current/bin
PI_ENTRY=\$HOME/$PI_PREFIX_REL/bin/pi

if [ ! -x "\$PI_RUNTIME_BIN/node" ] || [ ! -e "\$PI_ENTRY" ]; then
    printf 'pi: the installation is incomplete; run: ./install.sh --components pi\n' >&2
    exit 127
fi

PATH=\$PI_RUNTIME_BIN:\$PATH
export PATH
exec "\$PI_RUNTIME_BIN/node" "\$PI_ENTRY" "\$@"
EOF
}

# install_pi_policy <repo-root> - give Pi the shared agent policy.
#
# Pi reads its global instructions from <agent dir>/AGENTS.md. The policy has
# ONE source, config/agents/AGENTS.md in this repository, and every client gets
# a link to it. Claude and Codex are wired the same way.
install_pi_policy() {
    local repo_root=$1
    section 'Pi shared agent policy'
    # link_into creates the parent directory, so Pi's own directory is made
    # here and nothing else in it is touched.
    link_into "$repo_root/config/agents/AGENTS.md" "$PI_AGENT_DIR/AGENTS.md"
}

# pretty_home <path> - the path with the home directory written as "~".
pretty_home() {
    case $1 in
        "$HOME"/*) printf '~/%s' "${1#"$HOME"/}" ;;
        *) printf '%s' "$1" ;;
    esac
}

# install_host_pi <repo-root> - the whole host Pi installation.
install_host_pi() {
    local repo_root=$1

    if [ -f /run/.containerenv ] || [ -f /.dockerenv ]; then
        die "Pi is a host tool; there is one installation and it is not in a container"
    fi

    pi_manifest "$repo_root"
    install_pi_runtime
    install_pi_package
    install_pi_launcher "$repo_root"
    install_pi_policy "$repo_root"
    manual 'Sign in to Pi on the host: run "pi", then "/login" once for Claude Pro/Max and once for ChatGPT (Codex).'
}
