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

# --- the declaration that G8 compares the remote against ------------------
#
# G8 reads this file and the remote. The remote needs a network and a GitHub
# credential, so the checks here read the declaration only. They prove that
# the file G8 depends on exists, says what a ref name must say, and agrees
# with the default branch that the metadata manifest already declares.

PUB_REFS=$REPO_ROOT/manifests/published-refs.txt
PUB_META=$REPO_ROOT/manifests/github-metadata.json

pub_refs=$(sed -e 's/#.*//' -e 's/[[:blank:]]//g' "$PUB_REFS" 2>/dev/null | grep -v '^$')

check 'P9 the published-refs declaration exists' -- test -f "$PUB_REFS"

if [ -z "$pub_refs" ]; then
    fail 'P10 the declaration names only a full branch or tag ref' \
         'the declaration names no ref'
elif pub_bad=$(printf '%s\n' "$pub_refs" | grep -vE '^refs/(heads|tags)/[^ ]+$'); [ -n "$pub_bad" ]; then
    fail 'P10 the declaration names only a full branch or tag ref' \
         "$(printf '%s' "$pub_bad" | tr '\n' ' ')"
else
    pass "P10 the declaration names only a full branch or tag ref ($(printf '%s\n' "$pub_refs" | grep -c .) refs)"
fi

# A default branch that no ref declares makes G8 fail at publication time,
# where the cost of finding it is highest. The two manifests must agree.
pub_default=$(sed -n 's/.*"default_branch": *"\([^"]*\)".*/\1/p' "$PUB_META" | head -n 1)

if [ -z "$pub_default" ]; then
    fail 'P11 the declaration names the default branch' \
         'the metadata manifest declares no default branch'
elif printf '%s\n' "$pub_refs" | grep -Fxq -- "refs/heads/$pub_default"; then
    pass "P11 the declaration names the default branch (refs/heads/$pub_default)"
else
    fail 'P11 the declaration names the default branch' \
         "the metadata manifest declares $pub_default, which the declaration does not name"
fi

check_contains 'P12 the gate reads the declaration' \
    'manifests/published-refs.txt' "$(cat "$PUB_TOOL" 2>/dev/null || true)"

check_contains 'P13 the audit documents the declaration' \
    'manifests/published-refs.txt' "$(cat "$PUB_AUDIT" 2>/dev/null || true)"

# --- what G9 and G10 promise, without a network ---------------------------
#
# G9 builds the tracked tree and runs the installer against an empty home
# directory. G10 reads GitHub. The checks here read this file and the tree, so
# they state the properties that make both gates mean what they say.

pub_modes=$(sed -n "/^PUBLIC_MODES='/,/'$/p" "$PUB_TOOL" \
            | sed -e "s/^PUBLIC_MODES='//" -e "s/'$//" | grep -v '^$')

# G9 runs on the machine that publishes. A mode that installs would change it.
if [ -z "$pub_modes" ]; then
    fail 'P14 the gate runs only read-only installer modes' \
         'the gate declares no installer mode'
elif pub_writes=$(printf '%s\n' "$pub_modes" \
                  | grep -vE '^--(list|doctor|state|dry-run)( |$)'); [ -n "$pub_writes" ]; then
    fail 'P14 the gate runs only read-only installer modes' \
         "$(printf '%s' "$pub_writes" | tr '\n' ' ')"
else
    pass "P14 the gate runs only read-only installer modes ($(printf '%s\n' "$pub_modes" | grep -c .) modes)"
fi

# An untracked file on this machine must not be what makes the installer work,
# so the gate builds the tree from the commit rather than copying the checkout.
check_contains 'P15 the gate builds the tree from the tracked commit' \
    'git archive HEAD' "$(cat "$PUB_TOOL" 2>/dev/null || true)"

check_contains 'P16 the gate removes this machine XDG state from the run' \
    '-u XDG_CONFIG_HOME' "$(cat "$PUB_TOOL" 2>/dev/null || true)"

# --- the source list that G10 reads ---------------------------------------

PUB_SKILLS=$REPO_ROOT/manifests/skills.tsv

pub_sources=$(awk -F'\t' '$0 !~ /^#/ && NF > 1 { print $2 }' "$PUB_SKILLS" 2>/dev/null \
              | sort -u)

if [ -z "$pub_sources" ]; then
    fail 'P17 every source names one GitHub owner and repository' \
         "$PUB_SKILLS names no source repository"
elif pub_bad_src=$(printf '%s\n' "$pub_sources" \
                   | grep -vE '^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$'); [ -n "$pub_bad_src" ]; then
    fail 'P17 every source names one GitHub owner and repository' \
         "$(printf '%s' "$pub_bad_src" | tr '\n' ' ')"
else
    pass "P17 every source names one GitHub owner and repository ($(printf '%s\n' "$pub_sources" | grep -c .) sources)"
fi

# G10 claims to cover every repository an installation clones. That claim holds
# only while one command does the cloning, so the scope is a check too.
pub_cloners=$(grep -rlE 'git clone.*https://github\.com/' \
              "$REPO_ROOT/bin" "$REPO_ROOT/bootstrap" "$REPO_ROOT/components" \
              "$REPO_ROOT/lib" 2>/dev/null | sort)

check_eq 'P18 one command clones every source that G10 reads' \
    "$REPO_ROOT/bin/install-skills" "$pub_cloners"

unset PUB_SKILLS
unset pub_modes pub_writes pub_sources pub_bad_src pub_cloners

unset PUB_TOOL PUB_AUDIT PUB_REFS PUB_META
unset pub_listed pub_documented pub_audited pub_decision pub_refs pub_bad pub_default
