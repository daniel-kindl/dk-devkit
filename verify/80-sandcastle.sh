# 8. Sandcastle agent orchestration (agentbox)
#
# These checks never create a container. They prove that the definition is
# present and internally consistent, and that the boundary an unattended agent
# runs behind is actually in the code:
#
#   the real repository is never bind-mounted into a sandbox
#   only validated commits reach an agent/* branch
#   no credential value is ever an argument
#   only disposable per-run paths receive a container SELinux label
#
# The checks that need a running Podman are skipped when there is none, so a
# fresh machine still reports a clean run before "agentbox build".

section '8. Sandcastle agent orchestration'

AB=$REPO_ROOT/bin/agentbox
SC_DIR=$REPO_ROOT/config/sandcastle

# code_of <file...> - the file with its full-line comments removed.
#
# Every rule below is about what the code DOES. The prose in these files
# explains the same rules in words ("never mounts the real repository"), so a
# naive grep would match the explanation instead of the behaviour.
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
check 'A8 adversarial.mjs exists'            -- test -f "$SC_DIR/adversarial.mjs"
check 'A9 the credential shim exists'        -- test -f "$REPO_ROOT/containers/sandbox-web/bin/agent-cli-shim"
check 'A10 the credential shim parses'       -- sh -n "$REPO_ROOT/containers/sandbox-web/bin/agent-cli-shim"

if command -v node >/dev/null 2>&1; then
    check 'A11 orchestrate.mjs parses' -- node --check "$SC_DIR/orchestrate.mjs"
    check 'A12 selftest.mjs parses'    -- node --check "$SC_DIR/selftest.mjs"
    check 'A13 adversarial.mjs parses' -- node --check "$SC_DIR/adversarial.mjs"
else
    skip 'A11 orchestrate.mjs parses' 'no node on this side'
    skip 'A12 selftest.mjs parses'    'no node on this side'
    skip 'A13 adversarial.mjs parses' 'no node on this side'
fi

# --- the versions and the limits are pinned ---------------------------------

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
    manifest_timeout=$(sed -n 's/^AGENTBOX_TIMEOUT_SECONDS=//p' "$MANIFEST")
    case $manifest_timeout in
        [0-9]*) pass "B5 a wall-clock limit is configured (${manifest_timeout}s)" ;;
        *) fail 'B5 a wall-clock limit is configured' "got: [$manifest_timeout]" ;;
    esac
    manifest_commits=$(sed -n 's/^AGENTBOX_MAX_COMMITS=//p' "$MANIFEST")
    case $manifest_commits in
        [0-9]*) pass "B6 the import commit bound is configured ($manifest_commits)" ;;
        *) fail 'B6 the import commit bound is configured' "got: [$manifest_commits]" ;;
    esac
fi

# --- the boundaries hold ----------------------------------------------------

AB_CODE=$(code_of "$AB")
ORCH=$(code_of "$SC_DIR/orchestrate.mjs")
SELF=$(code_of "$SC_DIR/selftest.mjs")
ADV=$(code_of "$SC_DIR/adversarial.mjs")

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
    "$(printf '%s' "$AB_CODE" | grep -c 'security-opt label=disable')"

# No credential material may be mounted into a sandbox.
check_not_contains 'C5 agentbox never mounts .ssh'            '.ssh'         "$AB_CODE"
check_not_contains 'C6 agentbox never forwards SSH_AUTH_SOCK' 'SSH_AUTH_SOCK' "$AB_CODE"
check_not_contains 'C7 agentbox never mounts codex auth.json' 'auth.json'    "$AB_CODE"

# --- the real repository is never bind-mounted ------------------------------
#
# This is the boundary the whole design rests on. Every "-v" argument in
# agentbox must name the Podman socket, the disposable clone, or the per-run
# directory. A mount of ~/projects, of this checkout, or of the canonical
# skill store would put a canonical path back inside a container, and would
# relabel it as a side effect.

bad_mounts=$(printf '%s\n' "$AB_CODE" | grep -- '-v "' |
    grep -v '\$PODMAN_SOCKET' | grep -v '\$CLONE_HOST' |
    grep -v '\$RUN_DIR_HOST' || true)
check_eq 'C8 every bind mount is the socket, the clone or the run directory' '' \
    "$(printf '%s' "$bad_mounts" | tr -s '[:space:]' ' ')"

check_not_contains 'C9 the control plane never mounts ~/projects' \
    '-v "$PROJECTS_ROOT' "$AB_CODE"
check_not_contains 'C10 the control plane never mounts this checkout' \
    '-v "$REPO_ROOT_HOST' "$AB_CODE"
check_not_contains 'C11 no sandbox mounts the canonical skill store' \
    '-v "$SKILLS_DIR' "$AB_CODE"

# Every sandbox mount source is built from the run directory, so only
# disposable paths can receive the ":z" container label.
check_contains 'C12 the policy mount comes from the run directory' \
    'MOUNT_POLICY="$RUN_DIR_HOST/staging/policy"' "$AB_CODE"
check_contains 'C13 the skill mount comes from the run directory' \
    'MOUNT_SKILLS="$RUN_DIR_HOST/staging/skills"' "$AB_CODE"
check_contains 'C14 the credential mount comes from the run directory' \
    'MOUNT_CREDS="$RUN_DIR_HOST/creds"' "$AB_CODE"
check_contains 'C15 the sandbox mounts declare readonly' '"readonly": True' "$AB_CODE"
check_contains 'C16 the policy and the skills are copied, not mounted' \
    'stage_policy_and_skills' "$AB_CODE"

# --- the disposable clone ---------------------------------------------------
#
# A local clone hardlinks its object files by default, which would make the
# clone and the real repository share inodes. --no-hardlinks is what keeps a
# write inside the sandbox from reaching a real object.

check_contains 'D1 the clone copies objects instead of hardlinking them' \
    '--no-hardlinks' "$AB_CODE"
check_contains 'D2 the clone gets an empty template, so no sample hooks' \
    '--template="$RUN_DIR_VIEW/meta/empty-template"' "$AB_CODE"
check_contains 'D3 the clone keeps no remote pointing at the real repository' \
    'remote remove origin' "$AB_CODE"
check_contains 'D4 the orchestrator is told about the clone, not the repository' \
    '"repo": os.environ["CLONE"]' "$AB_CODE"
check_contains 'D5 the sandbox is proven not to hold the real repository path' \
    'forbiddenPaths' "$AB_CODE"
check_contains 'D6 the orchestrator probes every forbidden path' \
    'is absent from the sandbox' "$ORCH"
check_contains 'D7 the orchestrator checks the git directory is the clone' \
    'the git directory belongs to the disposable clone' "$ORCH"
# A sandbox image built before the credential shim existed would pass every
# other probe and still take its credential from the environment.
check_contains 'D8 the orchestrator refuses a stale sandbox image' \
    'STALE_IMAGE' "$ORCH"
check_contains 'D9 the selftest refuses a stale sandbox image' \
    'STALE_IMAGE' "$SELF"
# COPY writes as root whatever the current USER is, so the shim needs an
# explicit owner: a later RUN as "agent" cannot chmod a root-owned file.
check_contains 'D10 the credential shim is copied with an explicit owner' \
    'COPY --chown=agent:agent' \
    "$(code_of "$REPO_ROOT/containers/sandbox-web/Containerfile")"
# createSandbox() and exec() do no in-sandbox git identity setup; run() does.
check_contains 'D11 the selftest commit carries its own git identity' \
    'user.email=agentbox@localhost' "$SELF"
check_contains 'D12 the adversarial commit carries its own git identity' \
    'user.email=agentbox@localhost' "$ADV"

# --- the agent cannot reach main --------------------------------------------

check_not_contains 'E1 the orchestrator never pushes'     'git push'      "$ORCH"
check_not_contains 'E2 the orchestrator never merges'     'merge-to-head' "$ORCH"
check_not_contains 'E3 the orchestrator never opens a PR' 'gh pr create'  "$ORCH"
check_contains     'E4 the branch strategy is an explicit branch' 'branch: cfg.branch' "$ORCH"

# agentbox must refuse a branch outside the agent/ namespace. This runs the real
# argument parser; it exits before it touches Podman, so it creates nothing.
out=$("$AB" run --repo "$REPO_ROOT" --branch main --prompt-file "$SC_DIR/review-prompt.md" 2>&1 || true)
check_contains 'E5 agentbox refuses to work on main' 'refusing to use the branch' "$out"

out=$("$AB" run --repo "$REPO_ROOT" --branch feature/x --prompt-file "$SC_DIR/review-prompt.md" 2>&1 || true)
check_contains 'E6 agentbox refuses a non-agent branch' 'refusing to use the branch' "$out"

# agentbox must reject a name git would not accept as a ref, even when it
# carries the agent/ prefix. These exit before Podman is touched.
for bad in 'agent/../../escape' 'agent/' 'agent/has space'; do
    out=$("$AB" run --repo "$REPO_ROOT" --branch "$bad" \
              --prompt-file "$SC_DIR/review-prompt.md" 2>&1 || true)
    check_contains "E7 agentbox rejects the branch name [$bad]" \
        'not a usable branch name' "$out"
done

# --- only validated commits are imported ------------------------------------
#
# The transfer is the one place where something from the sandbox enters the
# real repository. Each of these checks removes one way that could go wrong.

check_contains 'F1 the result must descend from the base commit' \
    'merge-base --is-ancestor' "$AB_CODE"
check_contains 'F2 the number of imported commits is bounded' \
    'and the limit is $max' "$AB_CODE"
check_contains 'F3 a merge commit needs --allow-merges' \
    'rev-list --merges --count' "$AB_CODE"
check_contains 'F4 the objects are verified on arrival' \
    'fetch.fsckObjects=true' "$AB_CODE"
check_contains 'F5 the ref update is a compare and swap' \
    '"refs/heads/$branch" "$result" "$before"' "$AB_CODE"
check_contains 'F6 the fetched commit is compared with the validated one' \
    'the fetched commit is not the validated one' "$AB_CODE"
check_contains 'F7 the clone configuration is restored before the host reads it' \
    'clone-config.pristine' "$AB_CODE"
check_contains 'F8 the clone hooks are removed before the host reads it' \
    'rm -rf -- "$gitdir/hooks"' "$AB_CODE"
check_contains 'F9 the host git ignores every configuration the clone owns' \
    'GIT_CONFIG_GLOBAL=/dev/null' "$AB_CODE"
check_contains 'F10 the host git uses a hook directory the clone never saw' \
    'core.hooksPath=$RUN_DIR_VIEW/meta/no-hooks' "$AB_CODE"
check_contains 'F11 the repository is compared before and after the run' \
    'repo_snapshot "$REAL_REPO_VIEW" "$RUN_DIR_VIEW/meta/before"' "$AB_CODE"
check_contains 'F12 the import must move the agent branch and nothing else' \
    'the import changed more than the agent branch' "$AB_CODE"
check_contains 'F13 the baseline covers every ref' 'for-each-ref' "$AB_CODE"
check_contains 'F14 the baseline covers the git config' \
    'sha256sum < "$common/config"' "$AB_CODE"
check_contains 'F15 the baseline covers the git hooks' \
    'common/hooks' "$AB_CODE"
check_contains 'F16 the baseline covers the working tree' \
    'status --porcelain' "$AB_CODE"

# The orchestrator keeps its own defence-in-depth comparison of the clone.
check_contains 'F17 the orchestrator records a clone integrity baseline' \
    'snapshotIntegrity' "$ORCH"
check_contains 'F18 the orchestrator compares it after teardown' \
    'diffIntegrity(integrityBefore' "$ORCH"
check_contains 'F19 a clone integrity violation fails the run' \
    'DISPOSABLE CLONE INTEGRITY FAILED' "$ORCH"

# The adversarial selftest has to attack all four surfaces, or it proves
# nothing. These checks fail if any of them is ever dropped.
check_contains 'F20 the adversarial test writes a protected ref' \
    'git update-ref refs/heads/main' "$ADV"
check_contains 'F21 the adversarial test rewrites the git config' \
    'GITDIR/config' "$ADV"
check_contains 'F22 the adversarial test installs a hook' \
    'hooks/post-checkout' "$ADV"
check_contains 'F23 the adversarial test creates an arbitrary ref' \
    'refs/heads/agentbox-attacker' "$ADV"
check_contains 'F24 the adversarial test fails when the attack did not run' \
    'the attack did not run, so nothing was proven' "$AB_CODE"
check_contains 'F25 a corrupted result must be refused at import' \
    'a corrupted result is refused at import' "$AB_CODE"
check_contains 'F26 the SELinux labels are compared across a run' \
    'compare_labels' "$AB_CODE"

# The selftest force-deletes only a branch it made, in the agent/ namespace.
check_contains 'F27 the selftest only removes an agent/selftest- branch' \
    '"$AGENTBOX_BRANCH_PREFIX"selftest-*' "$AB_CODE"

# --- no credential value is ever an argument --------------------------------

check_not_contains 'G1 no credential is passed as -e NAME=VALUE' \
    '-e "CLAUDE_CODE_OAUTH_TOKEN=' "$AB_CODE"
check_not_contains 'G2 no API key is passed as -e NAME=VALUE' \
    '-e "ANTHROPIC_API_KEY=' "$AB_CODE"
check_not_contains 'G3 no OpenAI key is passed as -e NAME=VALUE' \
    '-e "OPENAI_API_KEY=' "$AB_CODE"
check_contains 'G4 the credential reaches a container as a 0600 file' \
    'chmod 600 -- "$f"' "$AB_CODE"
check_contains 'G5 the credential file is removed when the run ends' \
    'shred_credentials' "$AB_CODE"
check_not_contains 'G6 the orchestrator puts no credential in the sandbox env' \
    'env: sandboxEnv' "$ORCH"
check_contains 'G7 the sandbox proves the credential is not in its environment' \
    'the credential arrived as a file, not as an environment variable' "$ORCH"
# A sourced credential file is code. The shim parses it instead.
SHIM=$(code_of "$REPO_ROOT/containers/sandbox-web/bin/agent-cli-shim")
check_not_contains 'G8 the credential shim never sources the file' \
    '. "$CREDENTIAL_FILE"' "$SHIM"
check_contains 'G9 the credential shim exports parsed names only' \
    'export "$key=$value"' "$SHIM"
# An ambient credential must be asked for, never taken.
check_contains 'G10 an ambient credential is opt-in' \
    '--use-ambient-credentials) ambient=1' "$AB_CODE"
check_contains 'G11 load_secrets clears the ambient values by default' \
    "CLAUDE_CODE_OAUTH_TOKEN=''" "$AB_CODE"
# The credential mode check must not default to a safe-looking value.
check_not_contains 'G12 the credential mode check does not default to 600' \
    "|| printf '600'" "$AB_CODE"
check_contains 'G13 the run output is redacted before it is displayed' \
    '| redact' "$AB_CODE"
check_contains 'G14 the redaction values are exported, not passed as arguments' \
    'export "AGENTBOX_REDACT_$i=$v"' "$AB_CODE"

# --- runtime controls -------------------------------------------------------

check_contains 'H1 the run has a wall-clock limit' \
    'timeout --foreground --kill-after=30s "$timeout"' "$AB_CODE"
# "-i" makes the podman client read the terminal. From a background process
# group that takes SIGTTIN, which livelocks the attach loop and stalls the
# container's stdout. Nothing writes to the control plane's stdin.
check_not_contains 'H1a the control plane does not read the terminal' \
    'run --rm -i' "$AB_CODE"
check_contains 'H1b the control plane stdin is /dev/null' \
    '</dev/null 2>&1 | redact' "$AB_CODE"
check_contains 'H1c the wall-clock limit keeps the client in this process group' \
    'timeout --foreground' "$AB_CODE"
check_contains 'H2 a branch can only be claimed by one run' 'take_lock' "$AB_CODE"
check_contains 'H3 a stale lock is broken, not obeyed' \
    'breaking a stale lock' "$AB_CODE"
check_contains 'H4 a stale run directory is swept' \
    'removing stale run directory' "$AB_CODE"
check_contains 'H5 a multi-line --check is refused, not split' \
    'Put a multi-line check in a script and call the script.' "$AB_CODE"
check_contains 'H6 agentbox cleans up on INT and TERM' \
    "trap 'cleanup; exit 130' INT" "$AB_CODE"
check_contains 'H7 the cleanup removes the control plane' 'remove_runner' "$AB_CODE"
check_contains 'H8 the cleanup removes this run sandboxes' \
    'remove_run_sandboxes' "$AB_CODE"
check_contains 'H9 clean also sweeps control-plane containers' \
    'agentbox-runner-' "$AB_CODE"
# A fixed name collides: agentbox runs on the host and in the container, where
# the same PID exists in another namespace.
check_not_contains 'H10 the runner name is not just the PID' \
    'name "agentbox-runner-$$"' "$AB_CODE"

out=$("$AB" run --repo "$REPO_ROOT" --branch agent/verify-check \
          --prompt-file "$SC_DIR/review-prompt.md" \
          --check "$(printf 'a\nb')" --dry-run 2>&1 || true)
check_contains 'H11 a --check with a newline is rejected' \
    'must be a single line' "$out"

out=$("$AB" run --repo "$REPO_ROOT" --branch agent/verify-timeout \
          --prompt-file "$SC_DIR/review-prompt.md" --timeout 5 --dry-run 2>&1 || true)
check_contains 'H12 a too-short timeout is rejected' 'at least 60 seconds' "$out"

out=$("$AB" selftest --timeout 5 2>&1 || true)
check_contains 'H13 the selftest also takes a wall-clock limit' \
    'at least 60 seconds' "$out"

# --- a dry run works on a machine that is not set up yet --------------------
#
# "print the plan and change nothing" is most useful on the machine that has
# neither a Podman client, nor a built image, nor a credential. Requiring any
# of them would defeat the option.
DRY_PROMPT=$SC_DIR/review-prompt.md
out=$("$AB" run --repo "$REPO_ROOT" --branch agent/verify-dry-run \
          --prompt-file "$DRY_PROMPT" --dry-run 2>&1) && dry_rc=0 || dry_rc=$?
check_eq 'I1 a dry run exits 0 with no Podman and no image' '0' "$dry_rc"
check_contains 'I2 a dry run prints the plan' '"mode": "run"' "$out"
# The plan must not carry a credential into the terminal.
check_not_contains 'I3 the plan holds no credential' 'CLAUDE_CODE_OAUTH_TOKEN=' "$out"
# The plan must say, in the plan itself, that the repository is not mounted.
check_contains 'I4 the plan records that the repository is not mounted' \
    '"realRepositoryIsMounted": false' "$out"
check_contains 'I5 the plan names the disposable clone location' \
    '"disposableCloneUnder"' "$out"
check_contains 'I6 the plan carries the wall-clock limit' '"timeoutSeconds"' "$out"

# The isolation probes default to on, and --no-isolation-check turns them off.
check_contains 'I7 a plain run asserts isolation' '"assertIsolation": true' "$out"
out=$("$AB" run --repo "$REPO_ROOT" --branch agent/verify-dry-run \
          --prompt-file "$DRY_PROMPT" --no-isolation-check --dry-run 2>&1 || true)
check_contains 'I8 --no-isolation-check turns the probes off' \
    '"assertIsolation": false' "$out"

# --- nothing secret is tracked ----------------------------------------------

check 'J1 the credential file is not in the repository' -- \
    test ! -e "$REPO_ROOT/config/agentbox/secrets.env"
check 'J2 no run directory is tracked' -- \
    test ! -e "$REPO_ROOT/runs"

# --- the machine side, when Podman is reachable -----------------------------

if "$AB" doctor >/dev/null 2>&1; then
    pass 'K1 agentbox doctor reports a ready machine'
else
    doctor_out=$("$AB" doctor 2>&1 || true)
    case $doctor_out in
        *'podman client      NOT FOUND'*|*'podman reachable   NO'*)
            skip 'K1 agentbox doctor reports a ready machine' 'no Podman client on this side' ;;
        *'MISSING (run: agentbox build)'*)
            skip 'K1 agentbox doctor reports a ready machine' 'images not built yet' ;;
        *'claude credential  MISSING'*)
            skip 'K1 agentbox doctor reports a ready machine' 'no unattended Claude credential yet' ;;
        *)
            fail 'K1 agentbox doctor reports a ready machine' "${doctor_out//$'\n'/ | }" ;;
    esac
fi
