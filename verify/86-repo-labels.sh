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
