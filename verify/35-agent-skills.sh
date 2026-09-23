# 3e. The third-party agent skills the agent-skills component installs.
#
# This is the focused verification of the agent-skills component. It proves
# what manifests/skills.tsv declares, and the links that bin/sync-agent-skills
# writes for the two agent clients. The Codex native skills under .system
# belong to Codex, not to this component, and module 3c checks that they
# survive.

section '3e. Third-party agent skills'

STORE=$BOX_HOME/.agents/skills
CODEX_SKILLS=$BOX_HOME/.codex/skills

check 'S1 the canonical skill store exists' -- test -d "$STORE"

# Claude reads the whole store through one directory symlink.
check_link 'S2 ~/.claude/skills -> the canonical store' \
    "$BOX_HOME/.claude/skills" "$STORE"

missing=''
count=0
while IFS=$'\t' read -r name _source _ref _path; do
    case ${name:-} in ''|'#'*) continue ;; esac
    count=$(( count + 1 ))
    [ -f "$STORE/$name/SKILL.md" ] || missing="$missing $name"
done < "$REPO_ROOT/manifests/skills.tsv"
if [ -z "$missing" ]; then
    pass "S3 every skill in manifests/skills.tsv is installed ($count skills)"
else
    fail 'S3 every skill in manifests/skills.tsv is installed' "missing:$missing" \
        './install.sh --components agent-skills'
fi

# Codex needs one symlink per declared skill. Other directories in the store
# can come from plugins and have their own lifecycle.
broken=''
while IFS=$'\t' read -r name _source _ref _path; do
    case ${name:-} in ''|'#'*) continue ;; esac
    if [ ! -L "$CODEX_SKILLS/$name" ]; then
        broken="$broken $name"
    elif [ "$(readlink -f -- "$CODEX_SKILLS/$name")" != "$(readlink -f -- "$STORE/$name")" ]; then
        broken="$broken $name(wrong-target)"
    fi
done < "$REPO_ROOT/manifests/skills.tsv"
if [ -z "$broken" ]; then
    pass 'S4 Codex has a per-skill symlink for every declared skill'
else
    fail 'S4 Codex has a per-skill symlink for every declared skill' \
        "broken:$broken" 'run sync-agent-skills'
fi
