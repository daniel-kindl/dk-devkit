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
    # No terminal means no picker: an automated run reports what it needs and
    # stops, and never waits for an answer that cannot arrive.
    check 'C12 a selection is required without a terminal' -- \
        sh -c "'$INSTALLER' </dev/null >/dev/null 2>&1; test \$? = 2"
    check 'C13 an unknown component is refused (exit 3)' -- \
        sh -c "'$INSTALLER' --components ghost >/dev/null 2>&1; test \$? = 3"
    check_contains 'C14 a dry run says why a dependency is included' 'required by web-dev' \
        "$("$INSTALLER" --dry-run --components web-dev 2>/dev/null || true)"
    check_contains 'C14b a profile expands to the components it composes' 'required by minimal' \
        "$("$INSTALLER" --dry-run --profile minimal </dev/null 2>/dev/null || true)"
    check 'C14c an unknown profile is refused (exit 3)' -- \
        sh -c "'$INSTALLER' --profile ghost </dev/null >/dev/null 2>&1; test \$? = 3"
    check 'C14d a component is not accepted as a profile (exit 3)' -- \
        sh -c "'$INSTALLER' --profile devbox </dev/null >/dev/null 2>&1; test \$? = 3"

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
                'C12 a selection is required without a terminal' \
                'C13 an unknown component is refused (exit 3)' \
                'C14 a dry run says why a dependency is included' \
                'C14b a profile expands to the components it composes' \
                'C14c an unknown profile is refused (exit 3)' \
                'C14d a component is not accepted as a profile (exit 3)' \
                'C15 component installer tests pass'; do
        skip "$name" 'no python3 on this side'
    done
fi

# The host bootstrap and the component installer must converge the same state.
# They do that by calling the same library function, never by holding two
# copies of the same step.
for library in host-packages devbox environments agent-home pi; do
    check "C16 bootstrap/lib/$library.sh is shared" -- \
        test -f "$REPO_ROOT/bootstrap/lib/$library.sh"
done
check 'C17 the host bootstrap composes the libraries' -- \
    grep -q 'install_devbox_router "\$REPO_ROOT"' "$REPO_ROOT/bootstrap/host.sh"
check 'C18 the devbox component composes the same library' -- \
    grep -q 'install_devbox_router "\$REPO_ROOT"' "$REPO_ROOT/components/devbox/install.sh"
check 'C18b the host bootstrap composes the Pi library' -- \
    grep -q 'install_host_pi "\$REPO_ROOT"' "$REPO_ROOT/bootstrap/host.sh"
check 'C18c the pi component composes the same library' -- \
    grep -q 'install_host_pi "\$REPO_ROOT"' "$REPO_ROOT/components/pi/install.sh"

# The public/local state boundary. A component declares the tracked
# configuration it owns and the machine-local state it writes. Both sides are
# enforced, so the declaration stays a rule and does not decay into a comment.
# docs/components.md says why.
if command -v python3 >/dev/null 2>&1; then
    check_contains 'C20 --state reports the tracked configuration' \
        'public  manifests/github-labels.json' \
        "$("$INSTALLER" --state </dev/null 2>/dev/null || true)"
    check_contains 'C21 --state reports the machine-local state' \
        'local   ~/.local/share/distrobox-homes/web-dev/' \
        "$("$INSTALLER" --state </dev/null 2>/dev/null || true)"
    check 'C22 --state narrows to a selection' -- \
        sh -c "'$INSTALLER' --state --components repo-labels </dev/null 2>/dev/null | grep -q 'github-labels.json'"

    # A public path must exist here, and a local path must not. The second one
    # is the rule that keeps private state out of a public repository.
    check 'C23 every public path exists in the checkout' -- \
        python3 - "$REPO_ROOT" <<'PYEOF'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
missing = [
    f"{manifest.parent.name}: {entry}"
    for manifest in sorted(root.glob("components/*/component.json"))
    for entry in json.loads(manifest.read_text()).get("state", {}).get("public", [])
    if not (root / entry).exists()
]
if missing:
    print("\n".join(missing))
    sys.exit(1)
PYEOF
    check 'C24 no local path is tracked in the checkout' -- \
        python3 - "$REPO_ROOT" <<'PYEOF'
import json, pathlib, subprocess, sys
root = pathlib.Path(sys.argv[1])
tracked = set(subprocess.run(
    ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True,
).stdout.split())
leaked = []
for manifest in sorted(root.glob("components/*/component.json")):
    for entry in json.loads(manifest.read_text()).get("state", {}).get("local", []):
        inside = entry.removeprefix("~/").rstrip("/")
        if any(path == inside or path.startswith(inside + "/") for path in tracked):
            leaked.append(f"{manifest.parent.name}: {entry}")
if leaked:
    print("\n".join(leaked))
    sys.exit(1)
PYEOF
    check 'C25 no component names one machine home directory' -- \
        sh -c "! grep -rEq '\"(/home/|/var/home/|/Users/|/root/)' '$REPO_ROOT'/components/*/component.json"
else
    for name in 'C20 --state reports the tracked configuration' \
                'C21 --state reports the machine-local state' \
                'C22 --state narrows to a selection' \
                'C23 every public path exists in the checkout' \
                'C24 no local path is tracked in the checkout' \
                'C25 no component names one machine home directory'; do
        skip "$name" 'no python3 on this side'
    done
fi

# --- a promised command is installed, and a shell resolves it ---------------
#
# A component of kind "tool" gives the user a command. The contract declares it
# in "commands", the installation puts it in ~/.local/bin, and the plan treats
# an absent one as not ready. These checks prove the same invariant on this
# machine, for every component at once, so that a future tool cannot repeat
# "bash: repo-labels: command not found" while its component reports ready.

if command -v python3 >/dev/null 2>&1; then
    check 'C26 a tool that ships bin/<id> promises it as a command' --         python3 - "$REPO_ROOT" <<'PYEOF'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
silent = []
for manifest in sorted(root.glob("components/*/component.json")):
    document = json.loads(manifest.read_text())
    if document.get("kind") != "tool":
        continue
    source = root / "bin" / document["id"]
    if not (source.is_file() and source.stat().st_mode & 0o111):
        continue
    if document["id"] not in document.get("commands", []):
        silent.append(f'{document["id"]}: bin/{document["id"]} is installed by nothing')
if silent:
    print("\n".join(silent))
    sys.exit(1)
PYEOF

    COMPONENT_COMMANDS=$(python3 - "$REPO_ROOT" <<'PYEOF'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
for manifest in sorted(root.glob("components/*/component.json")):
    document = json.loads(manifest.read_text())
    for command in document.get("commands", []):
        print(document["id"], command)
PYEOF
)
    while read -r component command; do
        [ -n "${command:-}" ] || continue
        if on_host test -x "$HOST_HOME/.local/bin/$command" 2>/dev/null; then
            pass "C27 host: $component installed the $command command"
        else
            fail "C27 host: $component installed the $command command"                  "$HOST_HOME/.local/bin/$command is absent or not executable"                  "run ./install.sh --components $component"
        fi
        if resolved=$(host_sh "command -v $command" 2>/dev/null) && [ -n "$resolved" ]; then
            pass "C28 a host shell resolves $command ($resolved)"
        else
            fail "C28 a host shell resolves $command"                  'the command is not on the PATH of a host login shell'
        fi
    done <<< "$COMPONENT_COMMANDS"
    unset COMPONENT_COMMANDS component command resolved
else
    skip 'C26 a tool that ships bin/<id> promises it as a command' 'no python3 on this side'
    skip 'C27 a promised command is installed on the host' 'no python3 on this side'
    skip 'C28 a host shell resolves a promised command' 'no python3 on this side'
fi

# Every profile this repository documents must exist, so that a documented
# --profile selection never fails on a clean machine.
for profile in minimal developer agent-dev daniel; do
    check "C19 the $profile profile is tracked" -- \
        test -f "$REPO_ROOT/components/$profile/component.json"
done
