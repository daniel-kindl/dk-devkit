# 1b. The reusable toolkit component architecture.

section '1b. Toolkit components'

INSTALLER=$REPO_ROOT/install.sh
RESOLVER=$REPO_ROOT/bin/toolkit-install
CAPABILITIES=$REPO_ROOT/manifests/capabilities.json
COMPONENT_TEST=$REPO_ROOT/verify/probes/components.test.py

check 'C1 install.sh is executable' -- test -x "$INSTALLER"
check 'C2 the resolver is executable' -- test -x "$RESOLVER"
check 'C3 the capability manifest exists' -- test -f "$CAPABILITIES"
check 'C4 the deterministic tests exist' -- test -f "$COMPONENT_TEST"
check 'C5 every component declares a contract' -- \
    sh -c 'test "$(ls -1d "$1"/components/*/ | wc -l)" = "$(ls -1 "$1"/components/*/component.json | wc -l)"' sh "$REPO_ROOT"
check 'C6 every component operation is executable' -- \
    sh -c '! find "$1/components" -name "*.sh" ! -perm -u+x | grep .' sh "$REPO_ROOT"
check 'C7 the installer collects no credential' -- \
    sh -c "! grep -Eq 'read -s|getpass|GH_TOKEN|GITHUB_TOKEN|ANTHROPIC_API_KEY' '$RESOLVER'"

if command -v python3 >/dev/null 2>&1; then
    check 'C8 the resolver compiles' -- python3 -m py_compile "$RESOLVER"
    check 'C9 the capability manifest is valid JSON' -- \
        python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$CAPABILITIES"

    # --list and --dry-run must never write. Both are checked here because the
    # component catalogue is the only place a plan can come from.
    check 'C10 --list reports the catalogue' -- "$INSTALLER" --list
    check_contains 'C11 the catalogue groups the components' 'Development environments' \
        "$("$INSTALLER" --list 2>/dev/null || true)"
    check 'C12 a selection is required' -- \
        sh -c "'$INSTALLER' >/dev/null 2>&1; test \$? = 2"
    check 'C13 an unknown component is refused (exit 3)' -- \
        sh -c "'$INSTALLER' --components ghost >/dev/null 2>&1; test \$? = 3"
    check_contains 'C14 a dry run says why a dependency is included' 'required by web-dev' \
        "$("$INSTALLER" --dry-run --components web-dev 2>/dev/null || true)"

    component_out=$(python3 "$COMPONENT_TEST" 2>&1) && component_rc=0 || component_rc=$?
    component_n=$(printf '%s\n' "$component_out" | sed -n 's/^Ran \([0-9]*\) test.*/\1/p')
    if [ "$component_rc" = 0 ]; then
        pass "C15 component installer tests pass ($component_n tests)"
    else
        fail 'C15 component installer tests pass' \
            "$(printf '%s\n' "$component_out" | grep -E '^(FAIL|ERROR):' | head -5 | tr '\n' ' ')"
    fi
else
    for name in 'C8 the resolver compiles' 'C9 the capability manifest is valid JSON' \
                'C10 --list reports the catalogue' 'C11 the catalogue groups the components' \
                'C12 a selection is required' 'C13 an unknown component is refused (exit 3)' \
                'C14 a dry run says why a dependency is included' \
                'C15 component installer tests pass'; do
        skip "$name" 'no python3 on this side'
    done
fi

# The host bootstrap and the component installer must converge the same state.
# They do that by calling the same library function, never by holding two
# copies of the same step.
for library in host-packages devbox environments agent-home; do
    check "C16 bootstrap/lib/$library.sh is shared" -- \
        test -f "$REPO_ROOT/bootstrap/lib/$library.sh"
done
check 'C17 the host bootstrap composes the libraries' -- \
    grep -q 'install_devbox_router "\$REPO_ROOT"' "$REPO_ROOT/bootstrap/host.sh"
check 'C18 the devbox component composes the same library' -- \
    grep -q 'install_devbox_router "\$REPO_ROOT"' "$REPO_ROOT/components/devbox/install.sh"
