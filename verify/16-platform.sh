# 1c. The platform capability abstraction and its distribution adapters.

section '1c. Platform adapters'

INSTALLER=$REPO_ROOT/install.sh
PLATFORMS=$REPO_ROOT/manifests/platforms.json
PLATFORM_LIB=$REPO_ROOT/bootstrap/lib/platform.sh
PLATFORM_TEST=$REPO_ROOT/verify/probes/platforms.test.py

check 'P1 the platform manifest exists' -- test -f "$PLATFORMS"
check 'P2 the shell adapter lookup exists' -- test -f "$PLATFORM_LIB"
check 'P3 the deterministic tests exist' -- test -f "$PLATFORM_TEST"

# A distribution-specific step belongs in manifests/platforms.json. Component
# logic and the shared bootstrap libraries must ask for a capability instead.
DISTRO_STEP='bazzite|ujust|rpm-ostree|apt-get|pacman|[^a-z]dnf[^a-z]'
check 'P4 no component logic names a distribution' -- \
    sh -c "! grep -rniE \"$DISTRO_STEP\" $REPO_ROOT/components/*/*.sh | grep ."
check 'P5 the shared libraries name no distribution' -- \
    sh -c "! grep -rniE \"$DISTRO_STEP\" $REPO_ROOT/bootstrap/lib/*.sh | grep ."

if command -v python3 >/dev/null 2>&1; then
    check 'P6 the platform manifest is valid JSON' -- \
        python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$PLATFORMS"
    # --doctor reports and never writes, so it is safe on any machine.
    check 'P7 --doctor reports the platform' -- "$INSTALLER" --doctor
    check_contains 'P8 the report names the capabilities' 'Capabilities' \
        "$("$INSTALLER" --doctor 2>/dev/null || true)"
    check_contains 'P9 the report says which component this machine supports' 'Components' \
        "$("$INSTALLER" --doctor 2>/dev/null || true)"
    check 'P10 an unknown capability is refused (exit 2)' -- \
        sh -c "'$INSTALLER' --hint ghost >/dev/null 2>&1; test \$? = 2"

    platform_out=$(python3 "$PLATFORM_TEST" 2>&1) && platform_rc=0 || platform_rc=$?
    platform_n=$(printf '%s\n' "$platform_out" | sed -n 's/^Ran \([0-9]*\) test.*/\1/p')
    if [ "$platform_rc" = 0 ]; then
        pass "P11 platform adapter tests pass ($platform_n tests)"
    else
        fail 'P11 platform adapter tests pass' \
            "$(printf '%s\n' "$platform_out" | grep -E '^(FAIL|ERROR):' | head -5 | tr '\n' ' ')"
    fi
else
    for name in 'P6 the platform manifest is valid JSON' \
                'P7 --doctor reports the platform' \
                'P8 the report names the capabilities' \
                'P9 the report says which component this machine supports' \
                'P10 an unknown capability is refused (exit 2)' \
                'P11 platform adapter tests pass'; do
        skip "$name" 'no python3 on this side'
    done
fi
