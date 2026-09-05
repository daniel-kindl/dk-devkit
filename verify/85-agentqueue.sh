# 8b. The GitHub backlog coordinator (agentqueue)
#
# agentqueue is the TRUSTED half of the unattended pipeline. It holds the
# authority a sandbox never gets: it reads issues, pushes branches, opens pull
# requests and merges them. These checks prove that the authority stays on this
# side of the boundary, and that the coordinator cannot reach past its own
# namespace.
#
#   no GitHub credential is ever handed to agentbox or to a sandbox
#   the coordinator pushes and deletes only inside the agent/ namespace
#   every write method is guarded, so a dry run cannot change durable state
#   the shipped policy defaults refuse an automatic merge until it is chosen
#
# The last group runs the real unit tests and the real integration test. The
# integration test makes a bare remote and a working clone in a temporary
# directory and removes both.

section '8b. GitHub backlog coordinator (agentqueue)'

AQ=$REPO_ROOT/bin/agentqueue
AQ_LIB=$REPO_ROOT/lib/agentqueue

# code_of is defined in verify/80-sandcastle.sh, which always runs first. A
# local copy keeps this module usable with "--only 85".
aq_code_of() {
    sed -E '/^[[:space:]]*(#|"""|\*)/d' "$@"
}

# --- the pieces exist -------------------------------------------------------

check 'A1 agentqueue is executable'          -- test -x "$AQ"
check 'A2 the package is present'            -- test -d "$AQ_LIB"
check 'A3 the default policy exists'         -- \
    test -f "$REPO_ROOT/config/agentqueue/policy.default.json"
check 'A4 the manifest exists'               -- test -f "$REPO_ROOT/manifests/agentqueue.env"
check 'A5 the unit tests exist'              -- \
    test -f "$REPO_ROOT/verify/probes/agentqueue-unit.test.py"
check 'A6 the integration test exists'       -- \
    test -f "$REPO_ROOT/verify/probes/agentqueue-integration.test.py"
check 'A7 the architecture document exists'  -- test -f "$REPO_ROOT/docs/agentqueue.md"

if command -v python3 >/dev/null 2>&1; then
    check 'A8 every module compiles' -- \
        python3 -m compileall -q "$AQ_LIB" "$AQ"
    check 'A9 the default policy is valid JSON' -- \
        python3 -c "import json,sys;json.load(open(sys.argv[1]))" \
            "$REPO_ROOT/config/agentqueue/policy.default.json"
    check 'A10 the default policy passes its own validation' -- \
        python3 -c "
import sys; sys.path.insert(0, sys.argv[1] + '/lib')
from agentqueue import policy
policy.load('/nonexistent', sys.argv[1] + '/config/agentqueue/policy.default.json')
" "$REPO_ROOT"
    check 'A11 the CLI reports its version' -- "$AQ" --version
else
    skip 'A8 every module compiles' 'no python3 on this side'
    skip 'A9 the default policy is valid JSON' 'no python3 on this side'
    skip 'A10 the default policy passes its own validation' 'no python3 on this side'
    skip 'A11 the CLI reports its version' 'no python3 on this side'
fi

# --- the manifest is pinned -------------------------------------------------

AQ_MANIFEST=$REPO_ROOT/manifests/agentqueue.env
if [ -f "$AQ_MANIFEST" ]; then
    ( . "$AQ_MANIFEST" ) >/dev/null 2>&1 &&
        pass 'B1 the manifest is a valid shell fragment' ||
        fail 'B1 the manifest is a valid shell fragment'
    check_eq 'B2 one issue at a time is the default' '1' \
        "$(sed -n 's/^AGENTQUEUE_MAX_PARALLEL=//p' "$AQ_MANIFEST")"
    aq_retries=$(sed -n 's/^AGENTQUEUE_MAX_RETRIES=//p' "$AQ_MANIFEST")
    case $aq_retries in
        [0-9]*) pass "B3 the retry budget is bounded ($aq_retries)" ;;
        *) fail 'B3 the retry budget is bounded' "got: [$aq_retries]" ;;
    esac
    aq_ci=$(sed -n 's/^AGENTQUEUE_CI_TIMEOUT_SECONDS=//p' "$AQ_MANIFEST")
    case $aq_ci in
        [0-9]*) pass "B4 the CI wait is bounded (${aq_ci}s)" ;;
        *) fail 'B4 the CI wait is bounded' "got: [$aq_ci]" ;;
    esac
    aq_fix=$(sed -n 's/^AGENTQUEUE_MAX_FIX_ROUNDS=//p' "$AQ_MANIFEST")
    case $aq_fix in
        [0-9]*) pass "B5 the in-sandbox repair loop is bounded ($aq_fix rounds)" ;;
        *) fail 'B5 the in-sandbox repair loop is bounded' "got: [$aq_fix]" ;;
    esac
fi

# --- the credential boundary ------------------------------------------------
#
# This is the reason the two tools are separate programs. agentqueue holds the
# GitHub authority and agentbox holds none of it. Every check below removes one
# way that could stop being true.

AQ_CODE=$(aq_code_of "$AQ_LIB"/*.py "$AQ")

check_not_contains 'C1 agentqueue never exports GH_TOKEN' 'GH_TOKEN' "$AQ_CODE"
check_not_contains 'C2 agentqueue never exports GITHUB_TOKEN' 'GITHUB_TOKEN' "$AQ_CODE"
check_not_contains 'C3 agentqueue never reads the gh token out of gh' \
    'auth token' "$AQ_CODE"
check_not_contains 'C4 agentqueue never reads the credential file agentbox uses' \
    'secrets.env' "$AQ_CODE"
check_not_contains 'C5 agentqueue never forwards the ssh-agent socket to a run' \
    'SSH_AUTH_SOCK=' "$AQ_CODE"
check_not_contains 'C6 agentqueue never passes an environment to agentbox' \
    'env=' "$(aq_code_of "$AQ_LIB/runner.py")"

# The agentbox command line is built in one place. It must carry the repository,
# the branch, the prompt file and the limits, and nothing else.
RUNNER_CODE=$(aq_code_of "$AQ_LIB/runner.py")
check_contains 'C7 agentbox is driven through its own CLI' '"pipeline",' "$RUNNER_CODE"
check_contains 'C8 the prompt reaches agentbox as a file' \
    '"--prompt-file", prompt_file' "$RUNNER_CODE"
check_contains 'C9 the run carries a wall-clock limit' '"--timeout"' "$RUNNER_CODE"
check_contains 'C10 the import bound is passed on' '"--max-commits"' "$RUNNER_CODE"
check_contains 'C11 the in-sandbox repair loop is bounded' \
    '"--max-fix-rounds"' "$RUNNER_CODE"

# A prompt is written for a sandbox to read. It must never name a credential.
PROMPT_CODE=$(cat "$AQ_LIB/prompts.py")
for needle in 'CLAUDE_CODE_OAUTH_TOKEN' 'ANTHROPIC_API_KEY' 'OPENAI_API_KEY'; do
    check_not_contains "C12 the prompt builder never names $needle" \
        "$needle" "$PROMPT_CODE"
done

# --- the coordinator cannot reach past the agent namespace ------------------

GITOPS_CODE=$(cat "$AQ_LIB/gitops.py")
check_contains 'D1 a push outside the agent namespace is refused' \
    'refusing to push' "$GITOPS_CODE"
check_contains 'D2 a local branch delete outside it is refused' \
    'refusing to delete' "$GITOPS_CODE"
check_contains 'D3 a remote branch delete outside it is refused' \
    'refusing to delete' "$(cat "$AQ_LIB/ghapi.py")"
check_not_contains 'D4 the coordinator never force-pushes' '"--force"' "$GITOPS_CODE"
check_not_contains 'D5 the coordinator never rewrites history' '"rebase"' "$GITOPS_CODE"
check_not_contains 'D5a it never resets the working tree' '"reset"' "$GITOPS_CODE"
check_not_contains 'D6 the coordinator never commits' '"commit"' "$GITOPS_CODE"
# New work always starts from the remote-tracking ref, so a checked-out base
# branch is never moved under the user.
check_contains 'D7 new work is based on the remote-tracking ref' \
    'refs/remotes/origin/' "$(cat "$AQ_LIB/coordinator.py")"

# --- the merge gates --------------------------------------------------------

COORD_CODE=$(cat "$AQ_LIB/coordinator.py")
check_contains 'E1 the merge re-reads the issue' \
    'the issue closed while the run was in progress' "$COORD_CODE"
check_contains 'E2 the merge compares the pull request head' \
    'the pull request head is' "$COORD_CODE"
check_contains 'E3 a merge conflict refuses the merge' \
    'has a merge conflict' "$COORD_CODE"
check_contains 'E4 an undecided mergeability refuses the merge' \
    'has not decided' "$COORD_CODE"
check_contains 'E5 the merge itself is a compare and swap' \
    '"sha": expected_sha' "$(cat "$AQ_LIB/ghapi.py")"
check_contains 'E6 the merge verifies that the pull request really merged' \
    'is not merged' "$COORD_CODE"
check_contains 'E7 a review that did not run is stated, not assumed' \
    'merge_is_permitted_without_review' "$COORD_CODE"
check_contains 'E8 the diff is scanned before anything is pushed' \
    '_require_clean_diff' "$COORD_CODE"
check_contains 'E9 a security failure stops the whole queue' \
    'SecurityStop' "$COORD_CODE"
check_contains 'E10 a merge is followed by a rescan' \
    'a merge can unblock' "$(cat "$AQ_LIB/coordinator.py")"

# --- a dry run cannot change durable state ---------------------------------
#
# Every write method must pass through the guard. A method that forgot it
# would change GitHub during a dry run, and the check below finds that
# statically rather than after the fact.

if command -v python3 >/dev/null 2>&1; then
    unguarded=$(python3 - "$AQ_LIB" <<'PY'
import ast, os, sys

lib = sys.argv[1]
writes = {
    "ghapi.py": {"add_label", "remove_label", "create_comment", "delete_comment",
                 "close_issue", "create_pull", "update_pull_body", "merge_pull",
                 "delete_branch"},
    "gitops.py": {"fetch", "push_branch", "delete_local_branch"},
}
missing = []
for filename, names in writes.items():
    tree = ast.parse(open(os.path.join(lib, filename)).read())
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in names:
            continue
        calls = [
            n.func.attr
            for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        ]
        if "_mutate" not in calls:
            missing.append(f"{filename}:{node.name}")
print(" ".join(sorted(missing)))
PY
)
    check_eq 'F1 every write method passes through the dry-run guard' '' "$unguarded"
else
    skip 'F1 every write method passes through the dry-run guard' 'no python3 on this side'
fi

# --- the shipped defaults are conservative ---------------------------------
#
# A repository opts in to an automatic merge. It is never the default, and a
# merge with no independent review is never an accident.

DEFAULTS=$REPO_ROOT/config/agentqueue/policy.default.json
if command -v python3 >/dev/null 2>&1 && [ -f "$DEFAULTS" ]; then
    defaults_out=$(python3 - "$DEFAULTS" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print(d.get("autoMerge"), d.get("mergeWithoutReview"), d.get("maxParallel"),
      d.get("requireCiChecks"), d.get("scanDiffForSecrets"),
      d.get("requireAgentAuthoredCommits"))
PY
)
    check_eq 'G1 the shipped defaults refuse an automatic merge' \
        'False False 1 True True True' "$defaults_out"
fi

# --- the tests --------------------------------------------------------------

if command -v python3 >/dev/null 2>&1; then
    unit_out=$(python3 "$REPO_ROOT/verify/probes/agentqueue-unit.test.py" 2>&1) &&
        unit_rc=0 || unit_rc=$?
    unit_n=$(printf '%s\n' "$unit_out" | sed -n 's/^Ran \([0-9]*\) test.*/\1/p')
    if [ "$unit_rc" = 0 ]; then
        pass "H1 the coordinator unit tests pass ($unit_n tests)"
    else
        fail 'H1 the coordinator unit tests pass' \
            "$(printf '%s\n' "$unit_out" | grep -E '^(FAIL|ERROR):' | head -5 |
               tr '\n' ' ')"
    fi

    int_out=$(python3 "$REPO_ROOT/verify/probes/agentqueue-integration.test.py" 2>&1) &&
        int_rc=0 || int_rc=$?
    int_n=$(printf '%s\n' "$int_out" | sed -n 's/^Ran \([0-9]*\) test.*/\1/p')
    if [ "$int_rc" = 0 ]; then
        pass "H2 the coordinator integration tests pass ($int_n tests)"
    else
        fail 'H2 the coordinator integration tests pass' \
            "$(printf '%s\n' "$int_out" | grep -E '^(FAIL|ERROR):' | head -5 |
               tr '\n' ' ')"
    fi
else
    skip 'H1 the coordinator unit tests pass' 'no python3 on this side'
    skip 'H2 the coordinator integration tests pass' 'no python3 on this side'
fi

# --- the machine side -------------------------------------------------------

if command -v gh >/dev/null 2>&1; then
    if gh auth status >/dev/null 2>&1; then
        pass 'I1 gh is authenticated on this side'
    else
        skip 'I1 gh is authenticated on this side' 'gh is not signed in yet'
    fi
else
    skip 'I1 gh is authenticated on this side' 'gh lives in the web-dev container'
fi

if [ -n "${SSH_AUTH_SOCK:-}" ] && [ -S "${SSH_AUTH_SOCK:-}" ]; then
    pass 'I2 an ssh-agent socket is available for the push'
else
    skip 'I2 an ssh-agent socket is available for the push' 'no forwarded agent here'
fi

check 'J1 no repository policy file is tracked here' -- \
    test ! -e "$REPO_ROOT/.agentqueue.json"
