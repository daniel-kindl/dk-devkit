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

check_contains 'M9 documentation explains a disabled surface' \
    'Turning a surface off' \
    "$(cat "$REPO_ROOT/docs/repo-meta.md" 2>/dev/null || true)"

# --- the manifest and the audit say the same thing about the settings ------
#
# F9 recorded the settings in a sentence, and the sentence was wrong about the
# wiki. Two records of the same settings drift, so compare them: the manifest
# is what "repo-meta sync" writes, and the F9 table is what a reader is told.

META_AUDIT=$REPO_ROOT/docs/public-release-audit.md

meta_documented=$(sed -n 's/^| `\([a-z_]*\)` | \([A-Za-z0-9._/-]*\) |.*/\1=\2/p' \
                  "$META_AUDIT" | LC_ALL=C sort)

if ! command -v python3 >/dev/null 2>&1; then
    skip 'M10 the manifest settings match the audit table' 'no python3 on this side'
elif [ -z "$meta_documented" ]; then
    fail 'M10 the manifest settings match the audit table' \
         'F9 of the audit holds no settings table'
else
    meta_declared=$(python3 -c 'import json, sys
settings = json.load(open(sys.argv[1])).get("settings", {})
for key, value in settings.items():
    shown = "on" if value is True else "off" if value is False else str(value)
    print(key + "=" + shown)' "$META_MANIFEST" | LC_ALL=C sort)
    if [ "$meta_declared" = "$meta_documented" ]; then
        pass "M10 the manifest settings match the audit table ($(printf '%s\n' "$meta_declared" | grep -c .) settings)"
    else
        fail 'M10 the manifest settings match the audit table' \
             "manifest: $(printf '%s' "$meta_declared" | tr '\n' ' ')audit: $(printf '%s' "$meta_documented" | tr '\n' ' ')"
    fi
fi

unset META_AUDIT meta_documented meta_declared

# --- the installed command, not the file in this checkout -------------------
#
# The component exists to give a user the repo-meta command. Proving that
# bin/repo-meta compiles proves the implementation; these checks prove the
# interface, in the shell where the documentation says to type the name.

META_COMMAND=$HOST_HOME_VIEW/.local/bin/repo-meta

check 'M11 the component installs the command' -- \
    test -x "$REPO_ROOT/components/repo-meta/install.sh"
check 'M12 the component reports readiness through the installed command' -- \
    grep -q '\.local/bin/repo-meta' "$REPO_ROOT/components/repo-meta/doctor.sh"
check 'M13 the contract declares the repo-meta command' -- \
    sh -c "grep -q '\"repo-meta\"' '$REPO_ROOT/components/repo-meta/component.json'"
check 'M14 the contract declares the gh capability' -- \
    sh -c "grep -q '\"gh\"' '$REPO_ROOT/components/repo-meta/component.json'"

if on_host test -x "$META_COMMAND" 2>/dev/null; then
    pass 'M15 host: ~/.local/bin/repo-meta is installed and executable'
    meta_resolved=$(host_sh 'command -v repo-meta' 2>/dev/null || true)
    if [ -n "$meta_resolved" ]; then
        pass "M16 a host login shell resolves repo-meta ($meta_resolved)"
    else
        fail 'M16 a host login shell resolves repo-meta' \
             'the command is installed, but ~/.local/bin is not on the host PATH'
    fi
    if host_sh "'$HOST_HOME/.local/bin/repo-meta' --help" >/dev/null 2>&1; then
        pass 'M17 the installed command answers on the host'
    else
        fail 'M17 the installed command answers on the host' \
             'the installed command did not print its help'
    fi
else
    fail 'M15 host: ~/.local/bin/repo-meta is installed and executable' \
         'run ./install.sh --components repo-meta on the host'
    skip 'M16 a host login shell resolves repo-meta' 'the command is not installed'
    skip 'M17 the installed command answers on the host' 'the command is not installed'
fi

unset META_COMMAND meta_resolved
