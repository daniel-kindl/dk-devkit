# 8. Sandcastle agent orchestration (agentbox)
#
# These checks never create a container. They prove that the definition is
# present and internally consistent, and that the safety rules that keep an
# unattended agent away from main are actually in the code.
#
# The checks that need a running Podman are skipped when there is none, so a
# fresh machine still reports a clean run before "agentbox build".

section '8. Sandcastle agent orchestration'

AB=$REPO_ROOT/bin/agentbox
SC_DIR=$REPO_ROOT/config/sandcastle

# code_of <file...> - the file with its full-line comments removed.
#
# Every rule below is about what the code DOES. The prose in these files
# explains the same rules in words ("never mounts ~/.ssh"), so a naive grep
# would match the explanation instead of the behaviour.
code_of() {
    sed -E '/^[[:space:]]*(#|\/\/|\*|\/\*)/d' "$@"
}

# --- the pieces exist -------------------------------------------------------

check 'A1 agentbox is executable'            -- test -x "$AB"
check 'A2 orchestrate.mjs exists'            -- test -f "$SC_DIR/orchestrate.mjs"
check 'A3 selftest.mjs exists'               -- test -f "$SC_DIR/selftest.mjs"
check 'A4 the default review prompt exists'  -- test -f "$SC_DIR/review-prompt.md"
check 'A5 the runner Containerfile exists'   -- test -f "$REPO_ROOT/containers/agent-runner/Containerfile"
check 'A6 the sandbox Containerfile exists'  -- test -f "$REPO_ROOT/containers/sandbox-web/Containerfile"
check 'A7 agentbox parses'                   -- bash -n "$AB"

if command -v node >/dev/null 2>&1; then
    check 'A8 orchestrate.mjs parses' -- node --check "$SC_DIR/orchestrate.mjs"
    check 'A9 selftest.mjs parses'    -- node --check "$SC_DIR/selftest.mjs"
else
    skip 'A8 orchestrate.mjs parses' 'no node on this side'
    skip 'A9 selftest.mjs parses'    'no node on this side'
fi

# --- the versions are pinned ------------------------------------------------

MANIFEST=$REPO_ROOT/manifests/sandcastle.env
check 'B1 the sandcastle manifest exists' -- test -f "$MANIFEST"
if [ -f "$MANIFEST" ]; then
    # shellcheck source=/dev/null
    ( . "$MANIFEST" ) >/dev/null 2>&1 &&
        pass 'B2 the manifest is a valid shell fragment' ||
        fail 'B2 the manifest is a valid shell fragment'
    # An unattended runner must not change behaviour because a release appeared.
    manifest_ver=$(sed -n 's/^SANDCASTLE_VERSION=//p' "$MANIFEST")
    case $manifest_ver in
        [0-9]*.[0-9]*.[0-9]*) pass "B3 Sandcastle is pinned exactly ($manifest_ver)" ;;
        *) fail 'B3 Sandcastle is pinned exactly' "got: [$manifest_ver]" ;;
    esac
    check_eq 'B4 the branch prefix is agent/' 'agent/' \
        "$(sed -n 's/^AGENTBOX_BRANCH_PREFIX=//p' "$MANIFEST")"
fi

# --- the boundaries hold ----------------------------------------------------

# Distrobox creates every container with --privileged. The control plane must
# not be one, so its image is a plain OCI image with a non-root user.
check_contains 'C1 the runner image drops to a non-root user' 'USER 1000:1000' \
    "$(code_of "$REPO_ROOT/containers/agent-runner/Containerfile")"
check_contains 'C2 the sandbox image drops to a non-root user' 'USER agent' \
    "$(code_of "$REPO_ROOT/containers/sandbox-web/Containerfile")"
check_not_contains 'C3 no Containerfile asks for privilege' '--privileged' \
    "$(code_of "$REPO_ROOT"/containers/*/Containerfile)"

# The sandboxes keep their SELinux confinement. Only the control plane relaxes
# it, and only because SELinux denies the connect() on the Podman socket.
check_eq 'C4 exactly one label=disable, on the control plane' '1' \
    "$(code_of "$AB" | grep -c 'security-opt label=disable')"

# No credential material may be mounted into a sandbox.
AB_CODE=$(code_of "$AB")
check_not_contains 'C5 agentbox never mounts .ssh'            '.ssh'         "$AB_CODE"
check_not_contains 'C6 agentbox never forwards SSH_AUTH_SOCK' 'SSH_AUTH_SOCK' "$AB_CODE"
check_not_contains 'C7 agentbox never mounts codex auth.json' 'auth.json'    "$AB_CODE"

# ~/.agents must never be writable-mounted. The policy comes from this checkout
# and the skill store is read-only.
check_contains 'C8 the skill store is mounted read-only' ':ro' "$AB_CODE"
check_contains 'C9 the sandbox mounts declare readonly' '"readonly": True' "$AB_CODE"

# --- the agent cannot reach main --------------------------------------------

ORCH=$(code_of "$SC_DIR/orchestrate.mjs")
check_not_contains 'D1 the orchestrator never pushes'       'git push'      "$ORCH"
check_not_contains 'D2 the orchestrator never merges'       'merge-to-head' "$ORCH"
check_not_contains 'D3 the orchestrator never opens a PR'   'gh pr create'  "$ORCH"
check_contains     'D4 the branch strategy is an explicit branch' 'branch: cfg.branch' "$ORCH"

# agentbox must refuse a branch outside the agent/ namespace. This runs the real
# argument parser; it exits before it touches Podman, so it creates nothing.
out=$("$AB" run --repo "$REPO_ROOT" --branch main --prompt-file "$SC_DIR/review-prompt.md" 2>&1 || true)
check_contains 'D5 agentbox refuses to work on main' 'refusing to use the branch' "$out"

out=$("$AB" run --repo "$REPO_ROOT" --branch feature/x --prompt-file "$SC_DIR/review-prompt.md" 2>&1 || true)
check_contains 'D6 agentbox refuses a non-agent branch' 'refusing to use the branch' "$out"

# --- the branch prefix is a policy, and the repository is checked ----------
#
# Sandcastle's worktree sandbox mounts <repo>/.git read-write, so nothing
# inside the sandbox is PREVENTED from writing a ref outside agent/. The
# orchestrator therefore has to detect it: a baseline before the sandbox
# exists, a comparison after it is destroyed, and a failing run when they
# differ. These checks fail if that guard is ever removed.

check_contains 'D7 the orchestrator records an integrity baseline' \
    'snapshotIntegrity' "$ORCH"
check_contains 'D8 the orchestrator compares it after teardown' \
    'diffIntegrity(integrityBefore' "$ORCH"
check_contains 'D9 the baseline covers every ref' 'for-each-ref' "$ORCH"
check_contains 'D10 the baseline covers the local git config' \
    '"config", "--local", "--list"' "$ORCH"
check_contains 'D11 the baseline covers the git hooks' 'hookInventory' "$ORCH"
# A detected violation must FAIL the run, not merely be reported in the summary.
check_contains 'D12 an integrity violation fails the run' \
    'REPOSITORY INTEGRITY FAILED' "$ORCH"

# agentbox must reject a name git would not accept as a ref, even when it
# carries the agent/ prefix. These exit before Podman is touched.
for bad in 'agent/../../escape' 'agent/' 'agent/has space'; do
    out=$("$AB" run --repo "$REPO_ROOT" --branch "$bad" \
              --prompt-file "$SC_DIR/review-prompt.md" 2>&1 || true)
    check_contains "D13 agentbox rejects the branch name [$bad]" \
        'not a usable branch name' "$out"
done

# The selftest force-deletes its temporary branch. That must stay bounded to
# the agent/ namespace.
SELF=$(code_of "$SC_DIR/selftest.mjs")
check_contains 'D14 the selftest only force-deletes an agent/ branch' \
    'branch.startsWith("agent/")' "$SELF"

# --- an interrupted run leaves nothing behind -------------------------------
#
# "podman run --rm" only removes the container when the client exits cleanly.
# A control plane that outlives its run still holds the credential in its
# environment, so agentbox traps the signals and "agentbox clean" sweeps what
# a killed process could not.

check_contains 'G1 agentbox removes the runner on INT'  'trap' "$AB_CODE"
check_contains 'G2 the runner teardown is a real removal' 'remove_runner' "$AB_CODE"
check_contains 'G3 clean also sweeps control-plane containers' \
    'agentbox-runner-' "$AB_CODE"
# A fixed name collides: agentbox runs on the host and in the container, where
# the same PID exists in another namespace.
check_not_contains 'G4 the runner name is not just the PID' \
    'name "agentbox-runner-$$"' "$AB_CODE"

# --- a dry run works on a machine that is not set up yet --------------------
#
# "print the plan and change nothing" is most useful on the machine that has
# neither a Podman client, nor a built image, nor a credential. Requiring any
# of them would defeat the option.
DRY_PROMPT=$SC_DIR/review-prompt.md
out=$("$AB" run --repo "$REPO_ROOT" --branch agent/verify-dry-run \
          --prompt-file "$DRY_PROMPT" --dry-run 2>&1) && dry_rc=0 || dry_rc=$?
check_eq 'G7 a dry run exits 0 with no Podman and no image' '0' "$dry_rc"
check_contains 'G8 a dry run prints the plan' '"mode": "run"' "$out"
# The plan must not carry a credential into the terminal.
check_not_contains 'G9 the plan holds no credential' 'CLAUDE_CODE_OAUTH_TOKEN=' "$out"

# The isolation probes default to on, and --no-isolation-check turns them off.
check_contains 'G10 a plain run asserts isolation' '"assertIsolation": true' "$out"
out=$("$AB" run --repo "$REPO_ROOT" --branch agent/verify-dry-run \
          --prompt-file "$DRY_PROMPT" --no-isolation-check --dry-run 2>&1 || true)
check_contains 'G11 --no-isolation-check turns the probes off' \
    '"assertIsolation": false' "$out"

# --- the credential file is checked, not assumed ----------------------------
#
# A mode that cannot be read must refuse the file. Defaulting to "600" would
# pass a world-readable credential whenever stat is unavailable.
check_not_contains 'G5 the credential mode check does not default to 600' \
    "|| printf '600'" "$AB_CODE"

# The isolation probes are the evidence that no key material reached the
# sandbox. They have to be the default, not an opt-in.
check_contains 'G6 the isolation probes run by default' \
    'assert_isolation=1 dry_run=0' "$AB_CODE"

# --- nothing secret is tracked ----------------------------------------------

check 'E1 the credential file is not in the repository' -- \
    test ! -e "$REPO_ROOT/config/agentbox/secrets.env"
check_contains 'E2 the sandcastle scratch area is ignored' '.sandcastle/' \
    "$(code_of "$REPO_ROOT/.gitignore")"

# --- the machine side, when Podman is reachable -----------------------------

if "$AB" doctor >/dev/null 2>&1; then
    pass 'F1 agentbox doctor reports a ready machine'
else
    doctor_out=$("$AB" doctor 2>&1 || true)
    case $doctor_out in
        *'podman client      NOT FOUND'*|*'podman reachable   NO'*)
            skip 'F1 agentbox doctor reports a ready machine' 'no Podman client on this side' ;;
        *'MISSING (run: agentbox build)'*)
            skip 'F1 agentbox doctor reports a ready machine' 'images not built yet' ;;
        *'claude credential  MISSING'*)
            skip 'F1 agentbox doctor reports a ready machine' 'no unattended Claude credential yet' ;;
        *)
            fail 'F1 agentbox doctor reports a ready machine' "${doctor_out//$'\n'/ | }" ;;
    esac
fi
