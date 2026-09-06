# 8f. The publication gate
#
# The gate is the last thing that runs before this repository becomes public,
# so a silent defect in it is expensive. Every check here reads files and the
# local Git history. None of them needs this host, this container, a network,
# or a GitHub credential, so a contributor on any platform can run them:
#
#     ./verify.sh --only 88
#
# The gate itself is not run here. It runs "./verify.sh", and a suite that
# runs the command that runs the suite proves nothing.

section '8f. Publication gate'

PUB_TOOL=$REPO_ROOT/bin/publication-gate
PUB_AUDIT=$REPO_ROOT/docs/public-release-audit.md

check 'P1 publication-gate is executable' -- test -x "$PUB_TOOL"
check 'P2 publication-gate parses' -- bash -n "$PUB_TOOL"

# The gate reports. It must never be the thing that publishes, because then a
# rehearsal would change the repository.
check 'P3 the gate runs no command that changes the repository' -- \
    sh -c "! grep -Eq 'gh repo edit|gh api .*-X|--visibility|git push|git commit|repo-meta (sync|apply)' '$PUB_TOOL'"

# --- the gate list and the documented table say the same thing -------------
#
# Two lists of the same gates drift. The table in the audit is the reader's
# copy and "--list" is the tool's copy, so compare them instead of trusting
# that both were updated.

pub_listed=$(sh "$PUB_TOOL" --list 2>/dev/null | sed -n 's/^\(G[0-9]*\) .*/\1/p')
pub_documented=$(sed -n 's/^| \(G[0-9]*\) | .*/\1/p' "$PUB_AUDIT")

if [ -z "$pub_listed" ]; then
    fail 'P4 the gate list and the audit table name the same gates' \
         'publication-gate --list printed no gate'
elif [ "$pub_listed" = "$pub_documented" ]; then
    pass "P4 the gate list and the audit table name the same gates ($(printf '%s\n' "$pub_listed" | grep -c .) gates)"
else
    fail 'P4 the gate list and the audit table name the same gates' \
         "tool: $(printf '%s' "$pub_listed" | tr '\n' ' ') audit: $(printf '%s' "$pub_documented" | tr '\n' ' ')"
fi

# --- the values the gate reads out of the audit ---------------------------
#
# G7 parses this file. A heading or a table row rewritten in another change
# makes that parse return nothing, and an empty value must not read as a pass.

pub_audited=$(sed -n 's/^| Audited commit *| `\([0-9a-f]\{7,40\}\)` *|.*/\1/p' \
              "$PUB_AUDIT" | head -n 1)
pub_decision=$(sed -n '/^## Decision/,$p' "$PUB_AUDIT" \
               | grep -m1 -oE '\*\*(GO|NO-GO)\*\*' | tr -d '*')

if [ -z "$pub_audited" ]; then
    fail 'P5 the audit records a machine-readable audited commit' \
         'no "| Audited commit | `<sha>` |" row'
else
    pass 'P5 the audit records a machine-readable audited commit'
fi

check_eq 'P6 the audit records a machine-readable decision' GO "$pub_decision"

if [ -z "$pub_audited" ]; then
    skip 'P7 the audited commit is an ancestor of HEAD' 'no audited commit'
elif ! git -C "$REPO_ROOT" cat-file -e "$pub_audited^{commit}" 2>/dev/null; then
    skip 'P7 the audited commit is an ancestor of HEAD' \
         "$pub_audited is not in this checkout"
elif git -C "$REPO_ROOT" merge-base --is-ancestor "$pub_audited" HEAD; then
    pass 'P7 the audited commit is an ancestor of HEAD'
else
    fail 'P7 the audited commit is an ancestor of HEAD' \
         "the GO names $pub_audited, which this branch does not contain"
fi

check_contains 'P8 the audit documents the gate command' \
    'bin/publication-gate' "$(cat "$PUB_AUDIT" 2>/dev/null || true)"

unset PUB_TOOL PUB_AUDIT pub_listed pub_documented pub_audited pub_decision
