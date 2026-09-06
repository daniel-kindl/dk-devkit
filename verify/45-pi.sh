# 4b. The host Pi installation.
#
# This is the focused verification of the pi component. It proves the three
# facts that the component exists for:
#
#   1. Pi is installed, on the HOST, and runs there.
#   2. There is exactly ONE installation: no development environment has one.
#   3. The host still has no Node development toolchain. Pi's runtime is
#      private, and only the generated launcher puts it on a PATH.
#
# It reads the machine and never authenticates, so it prints no credential.

section '4b. Pi (host coding harness)'

PI_MANIFEST=$REPO_ROOT/manifests/pi.env
PI_COMPONENT=$REPO_ROOT/components/pi

check 'PI1 the Pi manifest is tracked (manifests/pi.env)' -- test -f "$PI_MANIFEST"
check 'PI2 the component contract is tracked' -- test -f "$PI_COMPONENT/component.json"
check 'PI3 the component operations are executable' -- \
    sh -c "test -x '$PI_COMPONENT/install.sh' && test -x '$PI_COMPONENT/doctor.sh'"
check 'PI4 the shared library is present (bootstrap/lib/pi.sh)' -- \
    test -f "$REPO_ROOT/bootstrap/lib/pi.sh"

if [ -f "$PI_MANIFEST" ]; then
    # shellcheck source=/dev/null
    . "$PI_MANIFEST"
else
    PI_RUNTIME_DIR_REL=.local/share/pi-node
    PI_PREFIX_REL=.local/share/pi/npm
    PI_LAUNCHER_REL=.local/bin/pi
    PI_AGENT_DIR_REL=.pi/agent
    PI_NODE_MIN_VERSION=22.19.0
fi

PI_LAUNCHER=$HOST_HOME_VIEW/$PI_LAUNCHER_REL
PI_RUNTIME_BIN=$HOST_HOME_VIEW/$PI_RUNTIME_DIR_REL/current/bin
PI_ENTRY=$HOST_HOME_VIEW/$PI_PREFIX_REL/bin/pi
PI_AGENT_DIR=$HOST_HOME_VIEW/$PI_AGENT_DIR_REL

# --- the installation -------------------------------------------------------

check 'PI5 host: the pi command is installed' -- test -x "$PI_LAUNCHER"
check 'PI6 host: the private Node runtime is installed' -- test -x "$PI_RUNTIME_BIN/node"
check 'PI7 host: the Pi package is installed in its own prefix' -- test -e "$PI_ENTRY"

if [ -x "$PI_RUNTIME_BIN/node" ]; then
    node_version=$("$PI_RUNTIME_BIN/node" --version 2>/dev/null | sed 's/^v//')
    if printf '%s\n%s\n' "$PI_NODE_MIN_VERSION" "$node_version" | sort -V -C; then
        pass "PI8 the private runtime satisfies Node >= $PI_NODE_MIN_VERSION ($node_version)"
    else
        fail "PI8 the private runtime satisfies Node >= $PI_NODE_MIN_VERSION" \
             "found: $node_version"
    fi
else
    skip "PI8 the private runtime satisfies Node >= $PI_NODE_MIN_VERSION" 'no runtime'
fi

# The observable behaviour, not the installer's internals: pi answers.
if on_host test -x "$PI_LAUNCHER" 2>/dev/null; then
    pi_version=$(host_sh "'$HOST_HOME/$PI_LAUNCHER_REL' --version" 2>/dev/null | tr -d '\r')
    if [ -n "$pi_version" ]; then
        pass "PI9 pi --version answers ($pi_version)"
    else
        fail 'PI9 pi --version answers' 'the launcher printed no version'
    fi
    resolved=$(host_sh 'command -v pi' 2>/dev/null || true)
    if [ -n "$resolved" ]; then
        pass "PI10 a host login shell resolves pi ($resolved)"
    else
        fail 'PI10 a host login shell resolves pi' \
             'the launcher is installed but ~/.local/bin is not on the host PATH'
    fi
else
    skip 'PI9 pi --version answers' 'pi is not installed'
    skip 'PI10 a host login shell resolves pi' 'pi is not installed'
fi

# --- exactly one installation ----------------------------------------------

# Pi is a host control-plane tool. A development environment must NOT own one:
# that is the whole point of the component, and it is what separates Pi from
# the claude and codex CLIs, which do live inside an environment.
#
# Distrobox forwards the host PATH verbatim, so the HOST launcher is visible
# from inside every environment. That is the one installation seen from the
# other side, not a second one. What must not exist is a pi inside the isolated
# container HOME or in the container's own system path.
for box in web-dev python-dev rust-dev; do
    box_home=$HOST_HOME_VIEW/.local/share/distrobox-homes/$box
    owned=$(find "$box_home" -maxdepth 4 -name pi -type f -perm -u+x 2>/dev/null || true)
    if [ -z "$owned" ]; then
        pass "PI11 $box owns no Pi installation (correct: there is exactly one, on the host)"
    else
        fail "PI11 $box owns no Pi installation" "found: $owned" \
             'Pi is a host tool. Remove the copy inside the environment.'
    fi

    # The host launcher that the forwarded PATH exposes must refuse to run
    # there, the same way the devbox shims refuse to route from inside a
    # container. A silent run would resolve every path against the wrong HOME.
    guarded=$(host_sh "distrobox enter -T --name $box -- pi --version 2>&1 || true" 2>/dev/null || true)
    check_contains "PI11b $box: the host launcher refuses to run inside a container" \
        'refusing to run inside a container' "$guarded"
done

# --- the host keeps no Node toolchain ---------------------------------------

if host_sh 'command -v node || command -v npm || command -v pnpm' >/dev/null 2>&1; then
    fail 'PI12 the Pi runtime is private to Pi' \
         "a host login shell resolves: $(host_sh 'command -v node; command -v npm; command -v pnpm' 2>/dev/null | tr '\n' ' ')" \
         'The Pi runtime must not be added to the host PATH.'
else
    pass 'PI12 the Pi runtime is private to Pi (no node, npm or pnpm in a host shell)'
fi

# --- the launcher is a launcher, not a router shim --------------------------

if [ -r "$PI_LAUNCHER" ]; then
    launcher_text=$(cat "$PI_LAUNCHER")
    check_not_contains 'PI13 the launcher does not route into a container' \
        'devbox agent' "$launcher_text"
    check_not_contains 'PI13b the launcher enters no container directly' \
        'distrobox' "$launcher_text"
    for name in TOKEN API_KEY PASSWORD SECRET CREDENTIAL; do
        check_not_contains "PI14 the launcher names no credential ($name)" \
            "$name" "$launcher_text"
    done
else
    skip 'PI13 the launcher does not route into a container' 'no launcher'
    skip 'PI13b the launcher enters no container directly' 'no launcher'
    skip 'PI14 the launcher names no credential' 'no launcher'
fi

# --- the shared policy has one source ---------------------------------------

check_link 'PI15 ~/.pi/agent/AGENTS.md -> the shared AGENTS.md' \
    "$PI_AGENT_DIR/AGENTS.md" "$REPO_ROOT/config/agents/AGENTS.md"

if [ -r "$PI_AGENT_DIR/AGENTS.md" ]; then
    a=$(sha256sum < "$PI_AGENT_DIR/AGENTS.md" | cut -d' ' -f1)
    b=$(sha256sum < "$REPO_ROOT/config/agents/AGENTS.md" | cut -d' ' -f1)
    check_eq 'PI16 Pi reads exactly the tracked policy file' "$b" "$a"
else
    skip 'PI16 Pi reads exactly the tracked policy file' 'the link is unreadable'
fi

# --- private state stays private --------------------------------------------

# Pi keeps its authentication, its trust decisions and its sessions in its own
# directory. None of it may ever be tracked here.
leaked=$(cd "$REPO_ROOT" && git ls-files | grep -E '(^|/)(auth\.json|trust\.json|sessions/|\.pi/)' || true)
if [ -z "$leaked" ]; then
    pass 'PI17 no Pi authentication, trust or session state is tracked'
else
    fail 'PI17 no Pi authentication, trust or session state is tracked' "$leaked"
fi

for name in auth.json trust.json; do
    target=$PI_AGENT_DIR/$name
    if [ -e "$target" ]; then
        mode=$(stat -c '%a' "$target" 2>/dev/null || echo '?')
        case $mode in
            600|400) pass "PI18 $name is readable by the owner only (mode $mode)" ;;
            *) fail "PI18 $name is readable by the owner only" "mode $mode" ;;
        esac
    else
        skip "PI18 $name is readable by the owner only" 'not created yet'
    fi
done

# --- no second routing system ------------------------------------------------

# Future work delegates a project command from Pi through the EXISTING devbox
# router. Until then nothing here may declare a second repository-to-environment
# mapping, and nothing may declare one afterwards either.
check 'PI19 the component adds no second environment mapping' -- \
    sh -c "! grep -rqE 'repos\.tsv|inference\.tsv|DEVBOX_ENV' '$PI_COMPONENT' '$REPO_ROOT/bootstrap/lib/pi.sh' '$PI_MANIFEST'"
