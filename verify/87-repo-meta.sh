# 8e. Canonical GitHub repository metadata

section '8e. Repository metadata tooling'

META_TOOL=$REPO_ROOT/bin/repo-meta
META_MANIFEST=$REPO_ROOT/manifests/github-metadata.json
META_TEST=$REPO_ROOT/verify/probes/repo-meta.test.py

check 'M1 repo-meta is executable' -- test -x "$META_TOOL"
check 'M2 the canonical metadata manifest exists' -- test -f "$META_MANIFEST"
check 'M3 the deterministic tests exist' -- test -f "$META_TEST"
check 'M4 the command stores no credential file' -- \
    sh -c "! grep -Eq 'GH_TOKEN|GITHUB_TOKEN|auth token|secrets\\.env' '$META_TOOL'"

if command -v python3 >/dev/null 2>&1; then
    check 'M5 repo-meta compiles' -- python3 -m py_compile "$META_TOOL"
    check 'M6 the manifest is valid JSON' -- \
        python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$META_MANIFEST"

    meta_out=$(python3 "$META_TEST" 2>&1) && meta_rc=0 || meta_rc=$?
    meta_n=$(printf '%s\n' "$meta_out" | sed -n 's/^Ran \([0-9]*\) test.*/\1/p')
    if [ "$meta_rc" = 0 ]; then
        pass "M7 repo-meta tests pass ($meta_n tests)"
    else
        fail 'M7 repo-meta tests pass' \
            "$(printf '%s\n' "$meta_out" | grep -E '^(FAIL|ERROR):' | head -5 | tr '\n' ' ')"
    fi
else
    skip 'M5 repo-meta compiles' 'no python3 on this side'
    skip 'M6 the manifest is valid JSON' 'no python3 on this side'
    skip 'M7 repo-meta tests pass' 'no python3 on this side'
fi

check_contains 'M8 documentation explains destructive sync' \
    'Removing a topic removes it from GitHub topic search' \
    "$(cat "$REPO_ROOT/docs/repo-meta.md" 2>/dev/null || true)"
