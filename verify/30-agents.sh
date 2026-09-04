# Agent CLIs, shared configuration wiring, skills and the Orca bridge.

section '3. Agent CLIs inside web-dev'

for tool in claude codex; do
    out=$(box_sh "command -v $tool" 2>/dev/null)
    if [ -z "$out" ]; then
        fail "$tool is installed in the box" 'run bootstrap/web-dev.sh'
    else
        check_contains "$tool lives in the isolated HOME" "distrobox-homes/$BOX_NAME" "$out"
    fi
done

section '3b. Shared agent configuration'

AGENTS_CANON=$REPO_ROOT/config/agents/AGENTS.md

check_link 'the box ~/.agents/AGENTS.md points at the repository' \
    "$BOX_HOME/.agents/AGENTS.md" "$AGENTS_CANON"
check_link 'the box ~/.agents/statusline points at the repository' \
    "$BOX_HOME/.agents/statusline" "$REPO_ROOT/config/agents/statusline"
check_link '~/.claude/CLAUDE.md -> the shared AGENTS.md' \
    "$BOX_HOME/.claude/CLAUDE.md" "$AGENTS_CANON"
check_link '~/.codex/AGENTS.md -> the shared AGENTS.md' \
    "$BOX_HOME/.codex/AGENTS.md" "$AGENTS_CANON"

if [ -r "$BOX_HOME/.claude/CLAUDE.md" ] && [ -r "$BOX_HOME/.codex/AGENTS.md" ]; then
    a=$(sha256sum < "$BOX_HOME/.claude/CLAUDE.md" | cut -d' ' -f1)
    b=$(sha256sum < "$BOX_HOME/.codex/AGENTS.md" | cut -d' ' -f1)
    c=$(sha256sum < "$AGENTS_CANON" | cut -d' ' -f1)
    if [ "$a" = "$b" ] && [ "$b" = "$c" ]; then
        pass 'Claude and Codex read exactly the same policy file'
    else
        fail 'Claude and Codex read exactly the same policy file' \
             "claude=$a codex=$b repo=$c"
    fi
else
    fail 'Claude and Codex read exactly the same policy file' 'one of the links is unreadable'
fi

section '3c. Skills'

STORE=$BOX_HOME/.agents/skills
check 'canonical skill store exists' -- test -d "$STORE"
check_link '~/.claude/skills -> the canonical store' "$BOX_HOME/.claude/skills" "$STORE"

missing=''
count=0
while IFS=$'\t' read -r name _source _ref _path; do
    case ${name:-} in ''|'#'*) continue ;; esac
    count=$(( count + 1 ))
    [ -f "$STORE/$name/SKILL.md" ] || missing="$missing $name"
done < "$REPO_ROOT/manifests/skills.tsv"
if [ -z "$missing" ]; then
    pass "every skill in manifests/skills.tsv is installed ($count skills)"
else
    fail 'every skill in manifests/skills.tsv is installed' "missing:$missing" \
         'run bin/install-skills'
fi

# Codex needs one symlink per skill, and its native skills must survive.
CODEX_SKILLS=$BOX_HOME/.codex/skills
broken=''
for name in $(cd "$STORE" 2>/dev/null && ls -1 2>/dev/null); do
    [ -d "$STORE/$name" ] || continue
    if [ ! -L "$CODEX_SKILLS/$name" ]; then
        broken="$broken $name"
    elif [ "$(readlink -f -- "$CODEX_SKILLS/$name")" != "$(readlink -f -- "$STORE/$name")" ]; then
        broken="$broken $name(wrong-target)"
    fi
done
if [ -z "$broken" ]; then
    pass 'Codex has a per-skill symlink for every skill in the store'
else
    fail 'Codex has a per-skill symlink for every skill in the store' \
         "broken:$broken" 'run sync-agent-skills'
fi

if [ -d "$CODEX_SKILLS/.system" ] && [ ! -L "$CODEX_SKILLS/.system" ]; then
    n=$(find "$CODEX_SKILLS/.system" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)
    pass "Codex native skills in .system are preserved ($n skills, real directory)"
else
    fail 'Codex native skills in .system are preserved' \
         "$CODEX_SKILLS/.system is missing or is a symlink"
fi

section '3d. Orca bridge'

if on_host test -x "$HOST_HOME/.local/bin/orca-ide"; then
    pass 'host: ~/.local/bin/orca-ide is present'
else
    fail 'host: ~/.local/bin/orca-ide is present' \
        'Orca registers this on Linux; the name avoids the GNOME Orca screen reader'
fi

for name in orca orca-ide; do
    check_link "box: ~/.local/bin/$name -> the tracked bridge wrapper" \
        "$BOX_HOME/.local/bin/$name" "$REPO_ROOT/config/web-dev/bin/orca-ide"
done

check 'box: the Orca bridge reaches the host' \
    -- box_sh 'command -v distrobox-host-exec >/dev/null'

check 'Orca worktree root exists (~/projects/.worktrees)' \
    -- on_host test -d "$HOST_HOME/projects/.worktrees"
