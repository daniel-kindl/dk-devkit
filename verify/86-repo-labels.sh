# 8d. Canonical GitHub repository labels

section '8d. Repository label tooling'

LABEL_TOOL=$REPO_ROOT/bin/repo-labels
LABEL_MANIFEST=$REPO_ROOT/manifests/github-labels.json
LABEL_TEST=$REPO_ROOT/verify/probes/repo-labels.test.py

check 'R1 repo-labels is executable' -- test -x "$LABEL_TOOL"
check 'R2 the canonical label manifest exists' -- test -f "$LABEL_MANIFEST"
check 'R3 the deterministic tests exist' -- test -f "$LABEL_TEST"
check 'R4 the command stores no credential file' -- \
    sh -c "! grep -Eq 'GH_TOKEN|GITHUB_TOKEN|auth token|secrets\\.env' '$LABEL_TOOL'"

if command -v python3 >/dev/null 2>&1; then
    check 'R5 repo-labels compiles' -- python3 -m py_compile "$LABEL_TOOL"
    check 'R6 the manifest is valid JSON' -- \
        python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$LABEL_MANIFEST"

    label_out=$(python3 "$LABEL_TEST" 2>&1) && label_rc=0 || label_rc=$?
    label_n=$(printf '%s\n' "$label_out" | sed -n 's/^Ran \([0-9]*\) test.*/\1/p')
    if [ "$label_rc" = 0 ]; then
        pass "R7 repo-labels tests pass ($label_n tests)"
    else
        fail 'R7 repo-labels tests pass' \
            "$(printf '%s\n' "$label_out" | grep -E '^(FAIL|ERROR):' | head -5 | tr '\n' ' ')"
    fi
else
    skip 'R5 repo-labels compiles' 'no python3 on this side'
    skip 'R6 the manifest is valid JSON' 'no python3 on this side'
    skip 'R7 repo-labels tests pass' 'no python3 on this side'
fi

check_contains 'R8 documentation explains destructive sync' \
    'Deleting labels removes them from issues and pull requests' \
    "$(cat "$REPO_ROOT/docs/repo-labels.md" 2>/dev/null || true)"

# --- the installed command, not the file in this checkout -------------------
#
# The component exists to give a user the repo-labels command. Proving that
# bin/repo-labels compiles proves the implementation; these checks prove the
# interface, in the shell where the documentation says to type the name.

LABEL_COMMAND=$HOST_HOME_VIEW/.local/bin/repo-labels

check 'R9 the component installs the command' -- \
    test -x "$REPO_ROOT/components/repo-labels/install.sh"
check 'R10 the component reports readiness through the installed command' -- \
    grep -q '\.local/bin/repo-labels' "$REPO_ROOT/components/repo-labels/doctor.sh"
check 'R11 the contract declares the repo-labels command' -- \
    sh -c "grep -q '\"repo-labels\"' '$REPO_ROOT/components/repo-labels/component.json'"
check 'R12 the contract declares the gh capability' -- \
    sh -c "grep -q '\"gh\"' '$REPO_ROOT/components/repo-labels/component.json'"

if on_host test -x "$LABEL_COMMAND" 2>/dev/null; then
    pass 'R13 host: ~/.local/bin/repo-labels is installed and executable'
    label_resolved=$(host_sh 'command -v repo-labels' 2>/dev/null || true)
    if [ -n "$label_resolved" ]; then
        pass "R14 a host login shell resolves repo-labels ($label_resolved)"
    else
        fail 'R14 a host login shell resolves repo-labels' \
             'the command is installed, but ~/.local/bin is not on the host PATH'
    fi
    if host_sh "'$HOST_HOME/.local/bin/repo-labels' --help" >/dev/null 2>&1; then
        pass 'R15 the installed command answers on the host'
    else
        fail 'R15 the installed command answers on the host' \
             'the installed command did not print its help'
    fi
else
    fail 'R13 host: ~/.local/bin/repo-labels is installed and executable' \
         'run ./install.sh --components repo-labels on the host'
    skip 'R14 a host login shell resolves repo-labels' 'the command is not installed'
    skip 'R15 the installed command answers on the host' 'the command is not installed'
fi

unset LABEL_COMMAND label_resolved
