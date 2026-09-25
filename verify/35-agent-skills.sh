# 3e. The third-party agent skills the agent-skills component installs.
#
# This is the focused verification of the agent-skills component. It proves
# the default profile resolves without ambiguity, every resolved skill exists
# in the canonical store, and the two agent clients see that store.

section '3e. Third-party agent skills'

STORE=$BOX_HOME/.agents/skills
CODEX_SKILLS=$BOX_HOME/.codex/skills
RESOLVED=$(mktemp)

if "$REPO_ROOT/bin/install-skills" --profile default --resolve > "$RESOLVED"; then
    count=$(awk -F '\t' 'NF && $1 !~ /^#/ { count++ } END { print count + 0 }' "$RESOLVED")
    duplicate=$(cut -f1 "$RESOLVED" | sort | uniq -d | head -n 1)
    if [ -z "$duplicate" ]; then
        pass "S1 default skill profile resolves without duplicate names ($count skills)"
    else
        fail 'S1 default skill profile resolves without duplicate names' \
            "duplicate: $duplicate" 'fix manifests/skill-profiles/default.tsv'
    fi
else
    fail 'S1 default skill profile resolves' \
        'bin/install-skills --profile default --resolve failed' \
        'fix the skill pack or profile manifests'
    : > "$RESOLVED"
fi

check 'S2 the canonical skill store exists' -- test -d "$STORE"

# Claude reads the whole store through one directory symlink.
check_link 'S3 ~/.claude/skills -> the canonical store' \
    "$BOX_HOME/.claude/skills" "$STORE"

missing=''
count=0
while IFS=$'\t' read -r name _source _ref _path _pack; do
    [ -n "${name:-}" ] || continue
    count=$(( count + 1 ))
    [ -f "$STORE/$name/SKILL.md" ] || missing="$missing $name"
done < "$RESOLVED"
if [ -z "$missing" ]; then
    pass "S4 every skill in the default profile is installed ($count skills)"
else
    fail 'S4 every skill in the default profile is installed' "missing:$missing" \
        './install.sh --components agent-skills'
fi

# Codex needs one symlink per selected skill. Other directories in the store
# can come from plugins and have their own lifecycle.
broken=''
while IFS=$'\t' read -r name _source _ref _path _pack; do
    [ -n "${name:-}" ] || continue
    if [ ! -L "$CODEX_SKILLS/$name" ]; then
        broken="$broken $name"
    elif [ "$(readlink -f -- "$CODEX_SKILLS/$name")" != "$(readlink -f -- "$STORE/$name")" ]; then
        broken="$broken $name(wrong-target)"
    fi
done < "$RESOLVED"
if [ -z "$broken" ]; then
    pass 'S5 Codex has a per-skill symlink for every selected skill'
else
    fail 'S5 Codex has a per-skill symlink for every selected skill' \
        "broken:$broken" 'run sync-agent-skills'
fi

check 'S6 install-skills has valid shell syntax' -- bash -n "$REPO_ROOT/bin/install-skills"

skill_help=$("$REPO_ROOT/bin/install-skills" --help)
if printf '%s\n' "$skill_help" | grep -q -- '--whole-machine' &&
   printf '%s\n' "$skill_help" | grep -q -- '--all-environments'; then
    pass 'S7 install-skills exposes machine-wide convergence'
else
    fail 'S7 install-skills exposes machine-wide convergence' \
        'help is missing --whole-machine or --all-environments'
fi

if grep -qF '"$toolkit_install" --environments' "$REPO_ROOT/bin/install-skills" &&
   ! grep -Eq '(^|[^A-Za-z-])(web-dev|python-dev|golang-dev|rust-dev|dotnet-dev|android-dev|godot-dev)([^A-Za-z-]|$)' \
       "$REPO_ROOT/bin/install-skills"; then
    pass 'S8 machine-wide convergence discovers environments from component modules'
else
    fail 'S8 machine-wide convergence discovers environments from component modules' \
        'use toolkit-install --environments; do not hard-code environment names'
fi

rm -f -- "$RESOLVED"
unset STORE CODEX_SKILLS RESOLVED missing broken count duplicate name _source _ref _path _pack skill_help