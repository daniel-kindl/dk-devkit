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
check 'A6a the output test exists'           -- \
    test -f "$REPO_ROOT/verify/probes/agentqueue-output.test.py"
check 'A6b the command surface test exists'  -- \
    test -f "$REPO_ROOT/verify/probes/agentqueue-cli.test.py"
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

# --- the presentation layer -------------------------------------------------
#
# The compact stage view is a display. It must render what the coordinator
# decided and it must never decide anything, it must never read a credential,
# and it must never turn a model's prose into a claim about the run.

UI_CODE=$(aq_code_of "$AQ_LIB/ui.py")
check_not_contains 'P1 the display reaches no GitHub client' 'self.github' "$UI_CODE"
check_not_contains 'P2 the display reaches no git wrapper'   'self.git' "$UI_CODE"
check_not_contains 'P3 the display starts no process'        'subprocess' "$UI_CODE"
check_not_contains 'P4 the display reads no file'            'open(' "$UI_CODE"
check_contains 'P5 a redirected stream is told apart from a terminal' \
    'self.tty' "$UI_CODE"
check_contains 'P6 a control sequence is only written in place' \
    'if self.in_place:' "$UI_CODE"
check_contains 'P7 a security failure has a marker of its own' \
    'Status.SECURITY' "$UI_CODE"
check_contains 'P8 the failure tail is bounded' 'max_tail_lines' "$UI_CODE"

# The progress channel is an exact prefix and a JSON document. A display built
# on a pattern against prose would report whatever a model chose to print.
MODEL_CODE=$(aq_code_of "$AQ_LIB/model.py")
check_contains 'P9 the progress channel is an exact prefix' \
    'line.startswith(AGENTBOX_EVENT_PREFIX)' "$MODEL_CODE"
check_contains 'P10 the progress payload is parsed as JSON' \
    'json.loads(payload)' "$MODEL_CODE"
check_not_contains 'P11 no progress is scraped out of prose with a pattern' \
    're.search' "$(aq_code_of "$AQ_LIB/coordinator.py" "$AQ_LIB/ui.py")"

# The run log is the evidence a compact run does not print. It is written as
# the child speaks, and only its owner can read it.
RUNNER_CODE_ALL=$(aq_code_of "$AQ_LIB/runner.py")
check_contains 'P12 the child stream is written to a log as it arrives' \
    'handle.write(line)' "$RUNNER_CODE_ALL"
check_contains 'P13 the run log is readable by its owner only' \
    '0o600' "$RUNNER_CODE_ALL"
check_contains 'P14 the queue transcript is readable by its owner only' \
    '0o600' "$(aq_code_of "$AQ_LIB/cli.py")"
check_contains 'P15 a dry run writes no transcript' '_NoRunLog' \
    "$(aq_code_of "$AQ_LIB/cli.py")"

# Two issues at a time means two threads reach the display and the progress
# bookkeeping. State that is per RUN must be per thread, or one issue reports
# another's progress, which is a wrong answer rather than a missing one.
COORD_CODE_ALL=$(aq_code_of "$AQ_LIB/coordinator.py")
CLI_CODE_ALL=$(aq_code_of "$AQ_LIB/cli.py")
check_contains 'P15a the phases one agentbox run reported are per thread' \
    'self._agent_events = threading.local()' "$COORD_CODE_ALL"
check_contains 'P15b the queue-wide counters are taken under a lock' \
    'with self._book:' "$COORD_CODE_ALL"
check_contains 'P15c the JSON stream attributes an event per thread' \
    'self._local = threading.local()' "$UI_CODE"
check_contains 'P15d the output modes are one group, --json included' \
    'level.add_argument("--json"' "$CLI_CODE_ALL"
check_contains 'P15e the run log serialises its writers' \
    'self._lock = threading.Lock()' "$CLI_CODE_ALL"

# One terminal and one run log, reached by several worker threads. Every write
# path of the renderers must sit inside the renderer lock, and a path added
# later must not be able to forget it. This finds that statically, the way F1
# finds a write method that skipped the dry-run guard, rather than hoping a
# timing test happens to catch the interleaving.
if command -v python3 >/dev/null 2>&1; then
    unlocked=$(python3 - "$AQ_LIB" <<'LOCKCHECK'
import ast, os, sys

WRITES = ("self._write(", "self._repaint(", "self._record(",
          "self.stream.write", "self._finish_pending(")
LOCKED = ("self._lock", "self._guard")

source = open(os.path.join(sys.argv[1], "ui.py")).read()
tree = ast.parse(source)
bad = []
for klass in tree.body:
    if not isinstance(klass, ast.ClassDef) or klass.name not in ("StageUi", "JsonUi"):
        continue
    for fn in klass.body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        guarded = set()
        for node in ast.walk(fn):
            if not isinstance(node, ast.With):
                continue
            head = (ast.get_source_segment(source, node) or "")[:80]
            if not any(name in head for name in LOCKED):
                continue
            for inner in ast.walk(node):
                guarded.add(id(inner))
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            call = ast.get_source_segment(source, node) or ""
            if not call.startswith(WRITES):
                continue
            if id(node) not in guarded:
                bad.append(f"{klass.name}.{fn.name}")
print(" ".join(sorted(set(bad))))
LOCKCHECK
)
    check_eq 'P15f every renderer write path is inside the renderer lock' \
        '' "$unlocked"
else
    skip 'P15f every renderer write path is inside the renderer lock' 'no python3'
fi

# The four levels exist, and they are the only four.
if command -v python3 >/dev/null 2>&1; then
    check_eq 'P16 the output levels are quiet, compact, verbose and debug' \
        "('quiet', 'compact', 'verbose', 'debug')" \
        "$(python3 -c "
import sys; sys.path.insert(0, sys.argv[1] + '/lib')
from agentqueue.ui import LEVELS
print(LEVELS)" "$REPO_ROOT")"
    check_eq 'P17 the stage model is the documented one' \
        'PLAN CLAIM IMPLEMENT CHECK REVIEW IMPORT PUSH PR CI MERGE DONE' \
        "$(python3 -c "
import sys; sys.path.insert(0, sys.argv[1] + '/lib')
from agentqueue.ui import Stage
print(' '.join(s.value for s in Stage))" "$REPO_ROOT")"
else
    skip 'P16 the output levels are quiet, compact, verbose and debug' 'no python3'
    skip 'P17 the stage model is the documented one' 'no python3'
fi

# agentbox publishes the events. The two halves must agree on the vocabulary.
ORCH_FILE=$REPO_ROOT/config/sandcastle/orchestrate.mjs
if [ -f "$ORCH_FILE" ]; then
    check_contains 'P18 the orchestrator publishes the progress channel' \
        '===AGENTBOX_EVENT===' "$(cat "$ORCH_FILE")"
    check_contains 'P19 agentbox publishes the host half of it' \
        '===AGENTBOX_EVENT===' "$(cat "$REPO_ROOT/bin/agentbox")"
    check_contains 'P20 the coordinator asks for the progress output mode' \
        '"--agent-output"' "$RUNNER_CODE_ALL"
    check_contains 'P21 agentbox accepts the output mode' \
        '--agent-output) agent_output=' "$(cat "$REPO_ROOT/bin/agentbox")"
fi

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

    out_out=$(python3 "$REPO_ROOT/verify/probes/agentqueue-output.test.py" 2>&1) &&
        out_rc=0 || out_rc=$?
    out_n=$(printf '%s\n' "$out_out" | sed -n 's/^Ran \([0-9]*\) test.*/\1/p')
    if [ "$out_rc" = 0 ]; then
        pass "H1a the output tests pass ($out_n tests)"
    else
        fail 'H1a the output tests pass' \
            "$(printf '%s\n' "$out_out" | grep -E '^(FAIL|ERROR):' | head -5 |
               tr '\n' ' ')"
    fi

    cli_out=$(python3 "$REPO_ROOT/verify/probes/agentqueue-cli.test.py" 2>&1) &&
        cli_rc=0 || cli_rc=$?
    cli_n=$(printf '%s\n' "$cli_out" | sed -n 's/^Ran \([0-9]*\) test.*/\1/p')
    if [ "$cli_rc" = 0 ]; then
        pass "H1b the command surface tests pass ($cli_n tests)"
    else
        fail 'H1b the command surface tests pass' \
            "$(printf '%s\n' "$cli_out" | grep -E '^(FAIL|ERROR):' | head -5 |
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
    skip 'H1a the output tests pass' 'no python3 on this side'
    skip 'H1b the command surface tests pass' 'no python3 on this side'
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

# --- the removed command stays removed --------------------------------------
#
# "drain" became "run". It is not an alias, not deprecated, not hidden and not
# a compatibility path, so the name must not survive anywhere a user reads or
# a parser looks. The behavioural proof is in agentqueue-cli.test.py; this is
# the static one, and it also covers the documentation the tests cannot read.
#
# The probes are excluded on purpose: they name the removed command in order
# to prove that it is refused.

aq_stale=$(grep -rIln --exclude-dir=.git --exclude-dir=__pycache__ \
    --exclude-dir=.worktrees --exclude='agentqueue-cli.test.py' \
    --exclude='85-agentqueue.sh' -e 'agentqueue drain' -e 'cmd_drain' \
    -- "$REPO_ROOT/bin" "$REPO_ROOT/lib" "$REPO_ROOT/docs" "$REPO_ROOT/config" \
       "$REPO_ROOT/manifests" "$REPO_ROOT/verify" "$REPO_ROOT/README.md" \
       "$REPO_ROOT/AGENTS.md" 2>/dev/null | tr '\n' ' ')
if [ -z "$aq_stale" ]; then
    pass 'J2 nothing still advertises the removed "drain" command'
else
    fail 'J2 nothing still advertises the removed "drain" command' "$aq_stale"
fi

if command -v python3 >/dev/null 2>&1; then
    check 'J3 "drain" is not a command the parser knows' -- \
        python3 -c "
import sys, argparse
sys.path.insert(0, sys.argv[1] + '/lib')
from agentqueue.cli import build_parser
found = set()
for action in build_parser()._actions:
    if isinstance(action, argparse._SubParsersAction):
        found.update(action.choices)
assert found == {'run', 'plan', 'doctor', 'policy', 'init'}, found
" "$REPO_ROOT"
    check 'J4 the help advertises run and never drain' -- \
        python3 -c "
import io, sys, contextlib
sys.path.insert(0, sys.argv[1] + '/lib')
from agentqueue.cli import build_parser
text = build_parser().format_help()
assert 'run' in text, text
assert 'drain' not in text.lower(), text
" "$REPO_ROOT"
else
    skip 'J3 "drain" is not a command the parser knows' 'no python3 on this side'
    skip 'J4 the help advertises run and never drain' 'no python3 on this side'
fi

# --- the host entry point ---------------------------------------------------
#
# The coordinator runs inside a container, because it needs gh and the
# forwarded ssh-agent. The COMMAND must still work from a normal host terminal:
#
#     cd ~/projects/dkkb
#     agentqueue run
#
# The host side is a devbox router shim and nothing else. These checks prove
# that it exists, that it delegates, that it carries the working directory and
# the arguments across unchanged, that the exit status comes back, that it
# cannot call itself, and that it adds nothing to the environment it delegates
# to.

section '8c. agentqueue host entry point'

AQ_ENV=$(sed -n 's/^AGENTQUEUE_ENVIRONMENT=//p' "$AQ_MANIFEST" | head -1 | tr -d '"'"'"' \t\r')
AQ_SHIM=$HOST_HOME/.local/bin/agentqueue
AQ_DEVBOX=$HOST_HOME/.local/bin/devbox

# The checks that ENTER the container run the coordinator this machine has
# installed, and that is a link into ONE checkout. When it is not the checkout
# under test - a linked worktree, or a branch that bootstrap has not seen - a
# behaviour check would report the installed version instead of the change, so
# it is skipped with that reason rather than answering about the wrong file.
# The comparison is "-ef", the same device and inode, and not string equality:
# the same file has several valid spellings here (/workspace and ~/projects,
# /home and /var/home, /run/host/... from inside the container).
AQ_LINK=$BOX_HOME/.local/bin/agentqueue
if [ -e "$AQ_LINK" ] && [ "$AQ_LINK" -ef "$REPO_ROOT/bin/agentqueue" ]; then
    AQ_LIVE=1; AQ_STALE=''
else
    AQ_LIVE=0
    AQ_STALE="the installed coordinator is $(readlink -f "$AQ_LINK" 2>/dev/null ||
              printf 'missing'), not this checkout"
fi

# The host spelling of this checkout. Only the host side can run the shim, and
# the host does not know the /workspace spelling.
AQ_CHECKOUT=$REPO_ROOT
case $REPO_ROOT in
    /workspace/*) AQ_CHECKOUT=$HOST_HOME/projects/${REPO_ROOT#/workspace/} ;;
    /run/host/*)  AQ_CHECKOUT=${REPO_ROOT#/run/host} ;;
esac

# --- the pin is configuration, not a constant in a script -------------------

if [ -n "$AQ_ENV" ]; then
    pass "K1 the manifest names the environment that owns the runtime ($AQ_ENV)"
else
    fail 'K1 the manifest names the environment that owns the runtime' \
        'AGENTQUEUE_ENVIRONMENT is missing from manifests/agentqueue.env'
fi
check "K2 the environment $AQ_ENV is configured for the router" -- \
    test -f "$REPO_ROOT/config/devbox-router/environments.d/$AQ_ENV.env"

# --- the shim is installed, and it is what the router generates today -------

if on_host test -x "$AQ_SHIM"; then
    pass 'K3 the host command ~/.local/bin/agentqueue exists and is executable'
else
    fail 'K3 the host command ~/.local/bin/agentqueue exists and is executable' \
        'run bootstrap/host.sh'
fi

aq_shim_now=$(on_host cat "$AQ_SHIM" 2>/dev/null || true)
aq_shim_want=$("$REPO_ROOT/bin/devbox" new-shim agentqueue --env "$AQ_ENV" --print 2>/dev/null || true)
if [ -z "$aq_shim_now" ]; then
    fail 'K4 the installed shim is exactly what the router generates' \
        'the shim is missing or unreadable'
elif [ "$aq_shim_now" = "$aq_shim_want" ]; then
    pass 'K4 the installed shim is exactly what the router generates'
else
    fail 'K4 the installed shim is exactly what the router generates' \
        'it has drifted; re-run bootstrap/host.sh'
fi

# --- it holds no runtime and no credential ----------------------------------
#
# A host shim is a router entry point. The host has no gh, no Node toolchain
# and no model credential, and this file must not be the thing that changes
# that.

check_contains 'K5 the shim delegates through the devbox router' \
    "exec \"\$router\" exec $AQ_ENV --cwd \"\$PWD\" -- agentqueue \"\$@\"" "$aq_shim_now"
check_not_contains 'K6 the shim contains no Python runtime' 'python' "$aq_shim_now"
for aq_needle in GH_TOKEN GITHUB_TOKEN CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_API_KEY \
                 OPENAI_API_KEY SSH_AUTH_SOCK secrets.env id_ed25519; do
    check_not_contains "K7 the shim never names $aq_needle" "$aq_needle" "$aq_shim_now"
done

# Nothing is exported, and the only assignment is the router path. A shim that
# set a variable would change the environment of the delegated process, and
# "the shim adds nothing" would stop being true.
aq_assignments=$(printf '%s\n' "$aq_shim_now" |
    grep -oE '^[[:space:]]*(export[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*=' |
    tr -d ' \t' | sort -u | tr '\n' ' ')
check_eq 'K8 the shim assigns nothing but the router path' 'router=' \
    "$(printf '%s' "$aq_assignments" | tr -d ' ')"

if [ -x "$REPO_ROOT/bin/scan-secrets" ]; then
    printf '%s\n' "$aq_shim_now" | "$REPO_ROOT/bin/scan-secrets" --stdin >/dev/null 2>&1 &&
        pass 'K9 the shim carries no credential' ||
        fail 'K9 the shim carries no credential' 'bin/scan-secrets reported a finding'
fi

# --- it delegates, and it carries the working directory across --------------
#
# DEVBOX_DRY_RUN makes the router print the plan instead of entering the
# container, so these checks start nothing.

aq_out=$(host_sh "cd '$HOST_HOME/projects' && DEVBOX_DRY_RUN=1 '$AQ_SHIM' plan --repo ." 2>&1)
check_contains "L1 the shim delegates into $AQ_ENV" "env=$AQ_ENV" "$aq_out"
check_contains 'L2 it is an explicit pin, not repository resolution' \
    'source=explicit' "$aq_out"
check_contains 'L3 ~/projects maps to the workspace inside the container' \
    'guest_cwd=/workspace' "$aq_out"
check_contains 'L4 argv[0] is the coordinator, not the shim' \
    'argv[0]=agentqueue' "$aq_out"
check_contains 'L5 --repo . reaches the coordinator unchanged' 'argv[3]=.' "$aq_out"

# The reported defect, as a path mapping: a repository under ~/projects on the
# host is the same repository under /workspace in the container. The name below
# is an example, not a configured repository: 'devbox path' maps a path whether
# or not it exists, and the space proves the mapping is not word-split.
check_eq 'L6 a host repository path maps to the shared workspace path' \
    '/workspace/a repo' \
    "$(on_host "$AQ_DEVBOX" path "$AQ_ENV" "$HOST_HOME/projects/a repo" 2>&1)"
check_eq 'L7 a directory outside the workspace maps through /run/host' \
    "/run/host$(on_host realpath -m "$HOST_HOME/.config" 2>/dev/null)" \
    "$(on_host "$AQ_DEVBOX" path "$AQ_ENV" "$HOST_HOME/.config" 2>&1)"

# The shim resolves NO repository. It carries the working directory across the
# boundary and the coordinator resolves the repository on the far side, from
# the TRANSLATED directory. A shim that resolved it here would hand over a host
# path that does not exist inside the container.
aq_out=$(host_sh "cd '$HOST_HOME/projects' && DEVBOX_DRY_RUN=1 '$AQ_SHIM' run" 2>&1)
check_contains 'L8 a run without --repo still delegates' "env=$AQ_ENV" "$aq_out"
check_contains 'L9 the translated directory is what crosses over' \
    'guest_cwd=/workspace' "$aq_out"
check_contains 'L10 argv is the command alone' 'argv[1]=run' "$aq_out"
if printf '%s\n' "$aq_out" | grep -q '^argv\[2\]='; then
    fail 'L11 the shim adds no --repo of its own' \
        "$(printf '%s\n' "$aq_out" | grep '^argv\[2\]=')"
else
    pass 'L11 the shim adds no --repo of its own'
fi
check_not_contains 'L12 the host path never crosses the boundary as an argument' \
    "argv[2]=$HOST_HOME" "$aq_out"

# --- argv survives verbatim -------------------------------------------------

aq_out=$(host_sh "cd '$HOST_HOME/projects' && DEVBOX_DRY_RUN=1 '$AQ_SHIM' run --repo 'a b' --label \"c'd\" --base 'e\"f'" 2>&1)
check_contains 'M1 an argument with a space survives'  'argv[3]=a b' "$aq_out"
check_contains 'M2 an argument with a quote survives'  "argv[5]=c'd" "$aq_out"
check_contains 'M3 an argument with a double quote survives' 'argv[7]=e"f' "$aq_out"

# --- the recursion guard ----------------------------------------------------
#
# The host shim must never be the thing that runs inside the container. Two
# defences: the shim refuses when it detects an environment, and the router
# strips the host shim directory from the container PATH.

aq_rc=0
host_sh "DEVBOX_ACTIVE_ENV=$AQ_ENV '$AQ_SHIM' --version" >/dev/null 2>&1 || aq_rc=$?
check_eq 'N1 the shim refuses inside an environment (exit 8)' '8' "$aq_rc"

if [ "$IN_CONTAINER" = 1 ]; then
    aq_rc=0
    "$HOST_HOME_VIEW/.local/bin/agentqueue" --version >/dev/null 2>&1 || aq_rc=$?
    check_eq 'N2 the shim refuses when it is run inside the container (exit 8)' \
        '8' "$aq_rc"

    aq_path=$(bash -lc 'command -v agentqueue' 2>/dev/null || true)
    case $aq_path in
        "$HOST_HOME_VIEW"/.local/bin/*)
            fail 'N3 agentqueue inside the container is the real command' \
                 "the host shim is on PATH here: $aq_path" ;;
        '') fail 'N3 agentqueue inside the container is the real command' \
                 'not on PATH; run bootstrap/web-dev.sh' ;;
        *)  pass "N3 agentqueue inside the container is the real command ($aq_path)" ;;
    esac
else
    skip 'N2 the shim refuses when it is run inside the container' 'host side'
    skip 'N3 agentqueue inside the container is the real command' 'host side'
fi

# --- the exit status and the resolved repository come back ------------------
#
# These enter the container for real. They read nothing from GitHub and they
# change nothing: "policy" resolves files, and a directory that is not a Git
# working tree is refused before anything else happens.

if on_host test -x "$AQ_SHIM" && [ "$AQ_LIVE" = 1 ]; then
    aq_out=$(host_sh "cd '$HOST_HOME/projects' && '$AQ_SHIM' policy --repo ." 2>&1); aq_rc=$?
    check_eq 'O1 a usage failure inside the container exits 2 on the host' '2' "$aq_rc"
    check_contains 'O2 --repo . resolved against the translated directory' \
        'not a Git working tree: /workspace' "$aq_out"

    # The same directory, with no --repo at all. The coordinator resolves it
    # from the working directory the router translated, so it refuses the same
    # container path and not the host one.
    aq_out=$(host_sh "cd '$HOST_HOME/projects' && '$AQ_SHIM' policy" 2>&1); aq_rc=$?
    check_eq 'O2a no --repo outside a repository exits 2 as well' '2' "$aq_rc"
    check_contains 'O2b it names the translated directory, not the host one' \
        'not a Git working tree: /workspace' "$aq_out"
    check_contains 'O2c it says how to name a repository elsewhere' \
        '--repo' "$aq_out"
    check_not_contains 'O2d the host spelling never appears in the refusal' \
        "$HOST_HOME/projects" "$aq_out"

    # The removed command. It is not an alias, not deprecated and not hidden,
    # so the parser refuses it the way it refuses any unknown word.
    aq_out=$(host_sh "cd '$HOST_HOME/projects' && '$AQ_SHIM' drain" 2>&1); aq_rc=$?
    check_eq 'O2e drain is rejected as an unknown command (exit 2)' '2' "$aq_rc"
    check_contains 'O2f the refusal names the commands that do exist' \
        'invalid choice' "$aq_out"

    aq_out=$(host_sh "'$AQ_SHIM' --version" 2>&1); aq_rc=$?
    check_eq 'O3 a success inside the container exits 0 on the host' '0' "$aq_rc"
    check_contains 'O4 the version comes from the coordinator, not the shim' \
        'agentqueue ' "$aq_out"

    if on_host test -e "$AQ_CHECKOUT/.git" &&
       host_sh "git -C '$AQ_CHECKOUT' remote get-url origin" >/dev/null 2>&1; then
        aq_out=$(host_sh "cd '$AQ_CHECKOUT' && '$AQ_SHIM' policy --repo ." 2>&1); aq_rc=$?
        check_eq 'O5 --repo . works from a repository on the host' '0' "$aq_rc"
        check_contains 'O6 it resolved this repository' 'repository' "$aq_out"

        # The point of the issue: standing in the repository is enough. The
        # answer must be the same one --repo . gives, through the same shim
        # and the same path translation.
        aq_bare=$(host_sh "cd '$AQ_CHECKOUT' && '$AQ_SHIM' policy" 2>&1); aq_rc=$?
        check_eq 'O7 no --repo works from a repository on the host' '0' "$aq_rc"
        check_eq 'O8 it resolves the same repository --repo . resolves' \
            "$aq_out" "$aq_bare"

        # And from a subdirectory of it, which --repo . could not do.
        if on_host test -d "$AQ_CHECKOUT/lib/agentqueue"; then
            aq_sub=$(host_sh "cd '$AQ_CHECKOUT/lib/agentqueue' && '$AQ_SHIM' policy" 2>&1)
            aq_rc=$?
            check_eq 'O9 no --repo works from a subdirectory too' '0' "$aq_rc"
            check_eq 'O10 a subdirectory resolves to the top of the tree' \
                "$aq_out" "$aq_sub"
        else
            skip 'O9 no --repo works from a subdirectory too' 'no lib/agentqueue'
            skip 'O10 a subdirectory resolves to the top of the tree' 'see O9'
        fi
    else
        skip 'O5 --repo . works from a repository on the host' \
             "no host checkout with an origin remote at $AQ_CHECKOUT"
        skip 'O6 it resolved this repository' 'see O5'
        skip 'O7 no --repo works from a repository on the host' 'see O5'
        skip 'O8 it resolves the same repository --repo . resolves' 'see O5'
        skip 'O9 no --repo works from a subdirectory too' 'see O5'
        skip 'O10 a subdirectory resolves to the top of the tree' 'see O5'
    fi
else
    aq_why=$AQ_STALE
    on_host test -x "$AQ_SHIM" || aq_why='no host shim'
    for aq_name in \
        'O1 a usage failure inside the container exits 2 on the host' \
        'O2 --repo . resolved against the translated directory' \
        'O2a no --repo outside a repository exits 2 as well' \
        'O2b it names the translated directory, not the host one' \
        'O2c it says how to name a repository elsewhere' \
        'O2d the host spelling never appears in the refusal' \
        'O2e drain is rejected as an unknown command (exit 2)' \
        'O2f the refusal names the commands that do exist' \
        'O3 a success inside the container exits 0 on the host' \
        'O4 the version comes from the coordinator, not the shim' \
        'O5 --repo . works from a repository on the host' \
        'O6 it resolved this repository' \
        'O7 no --repo works from a repository on the host' \
        'O8 it resolves the same repository --repo . resolves' \
        'O9 no --repo works from a subdirectory too' \
        'O10 a subdirectory resolves to the top of the tree'
    do
        skip "$aq_name" "${aq_why:-no host shim}"
    done
fi
