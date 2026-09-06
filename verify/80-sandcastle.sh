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
#   every disposable clone carries a Git identity of its own, and every other
#     change to its configuration is still a violation
#
# Two of the groups below are not static checks. They run the real create_clone
# and the real integrity comparison against real repositories in a scratch
# directory, with no container and no model credential.
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
    check 'A17 clone-integrity.mjs parses' -- node --check "$SC_DIR/clone-integrity.mjs"
else
    skip 'A11 orchestrate.mjs parses' 'no node on this side'
    skip 'A12 selftest.mjs parses'    'no node on this side'
    skip 'A13 adversarial.mjs parses' 'no node on this side'
    skip 'A17 clone-integrity.mjs parses' 'no node on this side'
fi

check 'A18 clone-integrity.mjs exists'       -- test -f "$SC_DIR/clone-integrity.mjs"
check 'A19 the clone identity probe is executable' -- \
    test -x "$REPO_ROOT/verify/probes/clone-identity.sh"
check 'A20 the clone identity probe parses' -- \
    bash -n "$REPO_ROOT/verify/probes/clone-identity.sh"

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
    # A clone with no identity is what made an agent write one of its own,
    # halfway through a run, into the git directory the baseline was taken from.
    manifest_git_name=$(sed -n 's/^AGENTBOX_GIT_NAME=//p' "$MANIFEST")
    manifest_git_email=$(sed -n 's/^AGENTBOX_GIT_EMAIL=//p' "$MANIFEST")
    if [ -n "$manifest_git_name" ] && [ -n "$manifest_git_email" ]; then
        pass "B7 the disposable clone identity is pinned ($manifest_git_name <$manifest_git_email>)"
    else
        fail 'B7 the disposable clone identity is pinned' \
            "name: [$manifest_git_name] email: [$manifest_git_email]"
    fi
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

# --- the disposable clone has a Git identity of its own ---------------------
#
# Sandcastle reads user.name and user.email out of the repository it drives and
# configures them inside the sandbox. A clone that carries neither leaves the
# agent CLI to write its own fallback identity into the clone's git directory,
# AFTER the orchestrator has recorded its integrity baseline, and an ordinary
# run is then reported as a run that changed the clone configuration.

check_contains 'D13 the clone is given a git identity' \
    'sgit config user.name "$AGENTBOX_GIT_NAME"' "$AB_CODE"
check_contains 'D14 the clone is given a git email' \
    'sgit config user.email "$AGENTBOX_GIT_EMAIL"' "$AB_CODE"
# It must be the clone. "git config --global" or a bare "git config" outside
# sgit would reach a configuration the host also reads.
check_not_contains 'D15 no global git config is ever written' \
    'config --global' "$AB_CODE"
check_contains 'D16 the orchestrator is told which identity to expect' \
    '"gitIdentity": {"name": os.environ["GIT_NAME"]' "$AB_CODE"
check_contains 'D17 the orchestrator refuses a clone with no identity' \
    'missingIdentity(integrityBefore.config, cfg.gitIdentity)' "$ORCH"
# The order is the whole fix: the identity has to be in the baseline, not a
# change measured against it.
identity_line=$(printf '%s\n' "$AB_CODE" | grep -n 'sgit config user.name' | cut -d: -f1)
pristine_line=$(printf '%s\n' "$AB_CODE" | grep -n 'meta/clone-config.pristine"$' | head -1 | cut -d: -f1)
if [ -n "$identity_line" ] && [ -n "$pristine_line" ] &&
   [ "$identity_line" -lt "$pristine_line" ]; then
    pass 'D18 the identity is set before the pristine configuration is saved'
else
    fail 'D18 the identity is set before the pristine configuration is saved' \
        "identity at line $identity_line, pristine copy at line $pristine_line"
fi

# A package manager must not put its store in the repository it installs for.
# pnpm does exactly that when its default store is on another device, which is
# always true for a bind-mounted worktree. The first real run left 18448
# untracked files in the clone, which is what made Sandcastle preserve the
# worktree at teardown.
SANDBOX_CF=$(code_of "$REPO_ROOT/containers/sandbox-web/Containerfile")
check_contains 'D19 the sandbox pins a pnpm store outside the repository' \
    'store-dir=/home/agent/.pnpm-store' "$SANDBOX_CF"
check_contains 'D20 that store lives in the sandbox home' \
    '/home/agent/.config/pnpm/rc' "$SANDBOX_CF"

# A worktree Sandcastle could not remove cleanly is PRESERVED, and that stays.
# What the run must also say is WHAT was left in it: bin/agentbox removes the
# whole run directory as soon as the run succeeds, so the path in the message
# points at nothing by the time a human reads the log.
INTEG=$(code_of "$SC_DIR/clone-integrity.mjs")
check_contains 'D21 a preserved worktree is reported by content' \
    'worktreeStatus' "$ORCH"
check_contains 'D22 the report keeps an untracked directory to one line' \
    'untracked-files=normal' "$INTEG"
check_not_contains 'D23 the orchestrator never cleans a preserved worktree' \
    'git clean' "$ORCH"

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
# take_lock and clean must share the rule. When they did not, a lock kept its
# run directory alive and the run directory kept the lock alive.
check_eq 'H3a one staleness rule, used by both take_lock and clean' '2' \
    "$(printf '%s' "$AB_CODE" | grep -c 'lock_is_stale "\$')"
check_contains 'H3b a lock whose process is gone is stale' \
    'kill -0 "$pid"' "$AB_CODE"
# A PID means nothing across the host/container boundary: the same number
# exists in both namespaces and names two different processes.
check_contains 'H3c the pid is only trusted on the side that recorded it' \
    '"$host" = "$(lock_host_id)"' "$AB_CODE"
# The age rule has to use the limit the run was actually given, not the
# manifest maximum, or a short run holds its branch far longer than it ran.
check_contains 'H3d the lock records the limit its run was given' \
    'ntimeout=%s' "$AB_CODE"
check_contains 'H3e the age rule uses that recorded limit' \
    "recorded=\$(printf '%s\\n' \"\$owner\" | sed -n 's/^timeout=//p')" "$AB_CODE"
check_contains 'H4 a finished run directory is swept' \
    'removing run directory' "$AB_CODE"
# A live branch lock, not the directory age, is what says a run is still going.
# A failed run keeps its directory on purpose, so age would keep it forever.
check_contains 'H4a a run that still holds its lock is kept' \
    'a run still holds its branch lock' "$AB_CODE"
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

# --- the implementation feedback loop ---------------------------------------
#
# A single-shot agent that is graded afterwards wastes a whole run on a typo.
# The orchestrator therefore runs the configured checks, feeds a failure back
# to the SAME agent in the SAME sandbox, and repeats up to --max-fix-rounds
# times. The loop must be bounded, it must not create a second sandbox, and
# the final verdict must read the LAST state of the checks.

check_contains 'M1 the sandbox re-runs the agent against a failing check' \
    'repair round' "$ORCH"
check_contains 'M2 the loop is bounded by maxFixRounds' \
    'summary.fixRounds < maxFixRounds' "$ORCH"
check_contains 'M3 the repair evidence is the failing command and its output' \
    'const fixPrompt' "$ORCH"
check_contains 'M4 the evidence is bounded' 'TAIL_BYTES' "$ORCH"
# One sandbox for the whole run. A second createSandbox would mean a second
# container, a second worktree and a lost session.
check_eq 'M5 the run creates exactly one sandbox' '1' \
    "$(printf '%s' "$ORCH" | grep -c 'await createSandbox(')"
check_contains 'M6 the verdict reads the final state of the checks' \
    'const finalChecks' "$ORCH"
check_contains 'M7 the final state is published for the coordinator' \
    'summary.failedChecks' "$ORCH"
check_contains 'M8 the manifest bounds the loop' 'AGENTBOX_MAX_FIX_ROUNDS' \
    "$(cat "$MANIFEST")"
check_contains 'M9 agentbox accepts --max-fix-rounds' '--max-fix-rounds)' "$AB_CODE"

# --- continuation mode ------------------------------------------------------
#
# A repair has to reach a branch that agentbox already imported. Making that
# branch its own base preserves every import invariant instead of working
# around one: the result still has to descend from the base, the range is
# still bounded, and the ref update is still a compare and swap.

check_contains 'N1 agentbox accepts --continue' '--continue) continuation=1' "$AB_CODE"
check_contains 'N2 continuation makes the branch its own base' \
    'base_ref=refs/heads/$branch' "$AB_CODE"
check_contains 'N3 continuation refuses a branch that does not exist' \
    'needs the branch $branch to exist already' "$AB_CODE"
check_contains 'N4 --continue and --base are mutually exclusive' \
    'cannot be used together' "$AB_CODE"

out=$("$AB" pipeline --repo "$REPO_ROOT" --branch agent/verify-continue \
          --prompt-file "$SC_DIR/review-prompt.md" --continue --dry-run 2>&1 || true)
check_contains 'N5 --continue refuses an absent branch at run time' \
    'to exist already' "$out"

out=$("$AB" pipeline --repo "$REPO_ROOT" --branch agent/verify-continue \
          --prompt-file "$SC_DIR/review-prompt.md" --continue --base main \
          --dry-run 2>&1 || true)
check_contains 'N6 --continue with --base is refused' 'cannot be used together' "$out"

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
check_contains 'I9 the plan names the identity the clone will carry' \
    '"cloneGitIdentity"' "$out"
check_contains 'I10 the plan records that the real config is not modified' \
    '"realRepositoryConfigIsModified": false' "$out"

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

# --- the comparison itself, run against real repositories -------------------
#
# Everything above reads the code. This runs it. verify/probes/ makes throwaway
# repositories in a scratch directory, calls the real create_clone and the real
# integrity comparison, and removes everything it made.

if command -v node >/dev/null 2>&1; then
    probe_out=$(node --test "$REPO_ROOT/verify/probes/clone-integrity.test.mjs" 2>&1) &&
        probe_rc=0 || probe_rc=$?
    probe_pass=$(printf '%s\n' "$probe_out" | sed -n 's/^# pass //p')
    probe_fail=$(printf '%s\n' "$probe_out" | sed -n 's/^# fail //p')
    if [ "$probe_rc" = 0 ] && [ "${probe_fail:-1}" = 0 ]; then
        pass "L1 the clone integrity comparison behaves ($probe_pass assertions)"
    else
        fail 'L1 the clone integrity comparison behaves' \
            "${probe_fail:-?} failed" \
            "$(printf '%s\n' "$probe_out" | grep -E '^not ok|Expected' | head -6 |
               tr '\n' ' ')"
    fi
else
    skip 'L1 the clone integrity comparison behaves' 'no node on this side'
fi

# --- the execution-efficiency budget ----------------------------------------
#
# The limit that measures WORK rather than silence. Sandcastle's idle timeout
# sees an agent that stops talking; this one sees an agent that stays busy and
# gets nowhere. A hard breach must stop the run and import NOTHING.

check 'P1 the budget module exists'          -- \
    test -f "$REPO_ROOT/config/sandcastle/budget.mjs"
check 'P2 the budget test exists'            -- \
    test -f "$REPO_ROOT/verify/probes/budget.test.mjs"
check 'P3 the module is staged into the run' -- \
    grep -q 'clone-integrity.mjs budget.mjs' "$AB"
check 'P4 the module is mounted read-only'   -- \
    grep -q 'staging/budget.mjs:/opt/workstation/sandcastle/budget.mjs:ro' "$AB"
check 'P5 the orchestrator meters the run'   -- \
    grep -q 'createBudgetMeter' "$SC_DIR/orchestrate.mjs"
check 'P6 a breach has its own exit code'    -- \
    grep -q "fail 12 'one model invocation passed its efficiency budget'" "$AB"
check 'P7 the manifest states every limit'   -- \
    grep -qE '^AGENTBOX_HARD_TOOL_CALLS=' "$REPO_ROOT/manifests/sandcastle.env"

out=$("$AB" run --repo "$REPO_ROOT" --branch agent/verify-dry-run \
          --prompt-file "$DRY_PROMPT" --dry-run 2>&1 || true)
check_contains 'P8 the plan states the budget' '"hardToolCalls"' "$out"

out=$("$AB" run --repo "$REPO_ROOT" --branch agent/verify-dry-run \
          --prompt-file "$DRY_PROMPT" --dry-run \
          --soft-tool-calls 60 --hard-tool-calls 30 2>&1 || true)
check_contains 'P9 a soft limit above its hard limit is refused' \
    'must be below' "$out"

if command -v node >/dev/null 2>&1; then
    probe_out=$(node --test "$REPO_ROOT/verify/probes/budget.test.mjs" 2>&1) &&
        probe_rc=0 || probe_rc=$?
    probe_pass=$(printf '%s\n' "$probe_out" | sed -n 's/^# pass //p')
    probe_fail=$(printf '%s\n' "$probe_out" | sed -n 's/^# fail //p')
    if [ "$probe_rc" = 0 ] && [ "${probe_fail:-1}" = 0 ]; then
        pass "P10 the efficiency budget behaves ($probe_pass assertions)"
    else
        fail 'P10 the efficiency budget behaves' \
            "${probe_fail:-?} failed" \
            "$(printf '%s\n' "$probe_out" | grep -E '^not ok|Expected' | head -6 |
               tr '\n' ' ')"
    fi
else
    skip 'P10 the efficiency budget behaves' 'no node on this side'
fi

probe_out=$("$REPO_ROOT/verify/probes/clone-identity.sh" 2>&1) && probe_rc=0 || probe_rc=$?
probe_pass=$(printf '%s\n' "$probe_out" | sed -n 's/^passed \([0-9]*\) .*/\1/p')
if [ "$probe_rc" = 0 ]; then
    pass "L2 a real disposable clone starts with the agent identity ($probe_pass checks)"
else
    fail 'L2 a real disposable clone starts with the agent identity' \
        "$(printf '%s\n' "$probe_out" | grep -A2 '  FAIL' | head -9 | tr '\n' ' ')"
fi

# --- the Podman client is provisioned, not assumed ---------------------------
#
# agentbox runs from inside web-dev, and Sandcastle's Podman provider calls a
# client there to create each sandbox on the host engine. The host needs no
# package for that; the container does, and nothing used to declare one. K1
# below cannot catch it, because a machine with no Podman is a legitimate
# state and K1 correctly skips. This check reads the declaration instead, so
# it fails on every machine when the requirement is dropped.
if grep -qx 'podman-remote' "$REPO_ROOT/manifests/web-dev-packages.txt"; then
    pass 'K0 the web-dev package manifest declares a Podman client'
else
    fail 'K0 the web-dev package manifest declares a Podman client' \
        'bin/agentbox runs inside web-dev and needs podman-remote there.' \
        'Add it to manifests/web-dev-packages.txt and distrobox/web-dev.ini.'
fi

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
