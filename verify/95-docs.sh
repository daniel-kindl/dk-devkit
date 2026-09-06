# The public documentation surface. A document that no index names is a
# document nobody finds, and a link that resolves to nothing is a broken
# promise to a reader of the public repository.
#
# Every check here reads files, plus the local Git remote. None of them needs
# this host, this container, or a network, so a contributor on any platform can
# run them:
#
#     ./verify.sh --only 95

section '10. Project documentation'

# doc_links <file> - print every relative Markdown link target of one file.
# An absolute URL, a mail address and a bare anchor are not link targets.
doc_links() {
    grep -oE '\]\([^)]+\)' -- "$1" 2>/dev/null \
        | sed -e 's/^](//' -e 's/)$//' -e 's/#.*$//' \
        | grep -vE '^(https?|mailto):' \
        | grep -v '^$'
}

# --- the files a public repository must have ------------------------------

docs_missing=''
for docs_want in README.md LICENSE SECURITY.md CONTRIBUTING.md docs/README.md; do
    [ -f "$REPO_ROOT/$docs_want" ] || docs_missing="$docs_missing $docs_want"
done
if [ -z "$docs_missing" ]; then
    pass 'the public project files exist'
else
    fail 'the public project files exist' "missing:$docs_missing"
fi

# --- every document is reachable from the index ---------------------------

docs_index=$REPO_ROOT/docs/README.md
if [ ! -f "$docs_index" ]; then
    skip 'every document is listed in the documentation index' \
         'docs/README.md does not exist'
else
    docs_listed=$(doc_links "$docs_index")
    docs_unlisted=''
    for docs_file in "$REPO_ROOT"/docs/*.md; do
        docs_base=$(basename "$docs_file")
        [ "$docs_base" = README.md ] && continue
        printf '%s\n' "$docs_listed" | grep -qxF "$docs_base" \
            || docs_unlisted="$docs_unlisted $docs_base"
    done
    if [ -z "$docs_unlisted" ]; then
        pass 'every document is listed in the documentation index'
    else
        fail 'every document is listed in the documentation index' \
             "not in docs/README.md:$docs_unlisted"
    fi

    if grep -qF '(docs/README.md)' "$REPO_ROOT/README.md"; then
        pass 'the project README links the documentation index'
    else
        fail 'the project README links the documentation index' \
             'README.md does not link docs/README.md'
    fi
fi

# --- every relative link resolves -----------------------------------------

docs_broken=''
for docs_file in "$REPO_ROOT"/*.md "$REPO_ROOT"/docs/*.md; do
    [ -f "$docs_file" ] || continue
    docs_dir=$(dirname "$docs_file")
    while IFS= read -r docs_target; do
        [ -n "$docs_target" ] || continue
        [ -e "$docs_dir/$docs_target" ] \
            || docs_broken="$docs_broken ${docs_file#"$REPO_ROOT"/} -> $docs_target;"
    done <<INNER
$(doc_links "$docs_file")
INNER
done
if [ -z "$docs_broken" ]; then
    pass 'every relative documentation link resolves'
else
    fail 'every relative documentation link resolves' "broken:$docs_broken"
fi

# --- the recorded repository name matches the tree and the remote ---------
#
# docs/naming.md is the deliberate naming decision that #24 requires. A rename
# is two operations: GitHub renames the repository, and the tree has to follow.
# GitHub redirects the old URL, so forgetting the second half is silent. These
# checks make it loud.

docs_naming=$REPO_ROOT/docs/naming.md
docs_name=$(sed -n 's/^| Decided repository name | `\([^`]*\)` |.*$/\1/p' \
            "$docs_naming" 2>/dev/null | head -n 1)

if [ -z "$docs_name" ]; then
    fail 'the naming decision records a repository name' \
         'docs/naming.md has no "Decided repository name" row'
else
    pass 'the naming decision records a repository name'

    # Every GitHub reference owned by the same account must name the decided
    # repository. A reference to another account is somebody else's repository.
    docs_owner=${docs_name%%/*}
    docs_wrong=''
    while IFS= read -r docs_ref; do
        [ -n "$docs_ref" ] || continue
        [ "$docs_ref" = "$docs_name" ] \
            || docs_wrong="$docs_wrong $docs_ref"
    done <<INNER
$(grep -rhoE "github\.com[:/]$docs_owner/[A-Za-z0-9_.-]+" \
       -- "$REPO_ROOT"/*.md "$REPO_ROOT"/docs/*.md 2>/dev/null \
     | sed -e "s#^github\.com[:/]##" -e 's/\.git$//' | sort -u)
INNER
    if [ -z "$docs_wrong" ]; then
        pass 'every tracked GitHub URL names the decided repository'
    else
        fail 'every tracked GitHub URL names the decided repository' \
             "recorded: $docs_name" "in the documentation:$docs_wrong"
    fi

    # The remote is the other half. A fork carries a different owner, so it
    # cannot answer this question and is skipped instead of failed.
    docs_remote=$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null \
                  | sed -e 's#^.*github\.com[:/]##' -e 's/\.git$//')
    if [ -z "$docs_remote" ]; then
        skip 'the origin remote is the decided repository' \
             'no origin remote on GitHub'
    elif [ "${docs_remote%%/*}" != "$docs_owner" ]; then
        skip 'the origin remote is the decided repository' \
             "origin is $docs_remote, a fork of $docs_name"
    else
        check_eq 'the origin remote is the decided repository' \
                 "$docs_name" "$docs_remote"
    fi
fi

unset -f doc_links
unset docs_missing docs_want docs_index docs_listed docs_unlisted \
      docs_file docs_base docs_dir docs_target docs_broken \
      docs_naming docs_name docs_owner docs_wrong docs_ref docs_remote
