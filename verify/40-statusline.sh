# The shared status line: specification, renderer, and both client adapters.

section '4. Status line'

SL=$REPO_ROOT/config/agents/statusline
check 'specification is tracked (config/agents/statusline/spec.json)' -- test -f "$SL/spec.json"
check 'specification is valid JSON' -- jq -e . "$SL/spec.json"
check 'renderer is executable' -- test -x "$SL/claude-render.sh"
check 'installer is executable' -- test -x "$SL/install.sh"

# The field order is the contract stated in config/agents/AGENTS.md and in
# config/agents/statusline/README.md. Keep this list, those two documents and
# spec.json in step: a field is added or removed in all four places at once.
order=$(jq -r '[.fields[].id] | join(",")' "$SL/spec.json" 2>/dev/null)
check_eq 'field order matches the documented contract' \
    'model,branch,pr,context,five_hour,week' "$order"

# The documented contract must render the same fields, in the same order, as
# spec.json. This catches a spec change that never reached the documentation.
# The model field is exempt: the documents spell it "<model + reasoning
# effort>", spec.json spells it "<model name> <reasoning effort>".
spec_render=$(jq -r '[.fields[] | select(.id != "model") | .render] | join(" | ")' \
    "$SL/spec.json" 2>/dev/null)
for doc in "$REPO_ROOT/config/agents/AGENTS.md" "$SL/README.md"; do
    label=${doc#"$REPO_ROOT/"}
    # The contract is an indented block that may wrap over several lines. Take
    # the block that starts at the model field and stops at the first blank
    # line, join it, then drop the model field itself.
    doc_render=$(awk '/<model \+ reasoning effort>/{f=1} f{if($0 ~ /^[[:space:]]*$/) exit; print}' \
        "$doc" 2>/dev/null \
        | tr '\n' ' ' | sed -e 's/[[:space:]][[:space:]]*/ /g' -e 's/^ //' -e 's/ $//' \
              -e 's/^<model + reasoning effort> | //')
    check_eq "documented field order matches spec.json ($label)" "$spec_render" "$doc_render"
done

# Claude: settings.json must invoke the renderer.
CLAUDE_SETTINGS=$BOX_HOME/.claude/settings.json
if [ -f "$CLAUDE_SETTINGS" ]; then
    cmd=$(jq -r '.statusLine.command // ""' "$CLAUDE_SETTINGS" 2>/dev/null)
    check_contains 'Claude statusLine invokes the shared renderer' 'claude-render.sh' "$cmd"
    # install.sh writes the path as "$HOME/..." when settings.json and the
    # renderer share one home, so that the same file works in the container
    # home and on the host. The shell that runs the status line expands it, so
    # expand it here too instead of testing the literal string.
    renderer=${cmd//\"/}
    resolved=$(HOME=$BOX_HOME sh -c "printf '%s' \"$renderer\"" 2>/dev/null)
    if [ -n "$resolved" ] && [ -x "$resolved" ]; then
        pass 'the configured renderer path is executable'
    else
        fail 'the configured renderer path is executable' \
             "configured: [$renderer]" "resolved:   [$resolved]"
    fi
    # Orca's hooks must still be there: the router mirrors them into the box.
    if jq -e '.hooks | length > 0' "$CLAUDE_SETTINGS" >/dev/null 2>&1; then
        pass 'Orca Claude hooks are present in the box settings'
    else
        skip 'Orca Claude hooks are present in the box settings' 'no hooks configured yet'
    fi
else
    fail 'Claude settings.json exists' "$CLAUDE_SETTINGS not found"
fi

# Renderer behaviour: it must survive an empty payload and render a real one.
if [ -x "$SL/claude-render.sh" ]; then
    out=$(printf '' | "$SL/claude-render.sh" 2>&1; printf 'rc=%s' "$?")
    check_contains 'renderer exits cleanly on an empty payload' 'rc=0' "$out"
    payload='{"model":{"display_name":"Opus 5"},"effort":{"level":"high"},
      "workspace":{"project_dir":"/workspace/demo","current_dir":"/workspace/demo"},
      "worktree":{"branch":"main"},"pr":{"number":7},
      "context_window":{"remaining_percentage":83,"total_input_tokens":12000,"total_output_tokens":500},
      "rate_limits":{"five_hour":{"used_percentage":10},"seven_day":{"used_percentage":25}}}'
    out=$(printf '%s' "$payload" | NO_COLOR=1 "$SL/claude-render.sh" 2>/dev/null)
    check_contains 'renderer emits the model and effort' 'Opus 5 high' "$out"
    check_contains 'renderer emits the branch'           'main'        "$out"
    check_contains 'renderer emits the PR number'        'PR #7'       "$out"
    check_contains 'renderer emits the context gauge'    'ctx 83% left' "$out"
    check_contains 'renderer emits the 5h gauge'         '5h 90% left'  "$out"
    check_contains 'renderer emits the week gauge'       'week 75% left' "$out"
    # The project field was removed from the contract. The payload above still
    # carries workspace.project_dir, so the renderer must ignore it.
    check_not_contains 'renderer omits the project'      'demo' "$out"
    check_eq 'renderer emits exactly the contracted field count' \
        "$(jq -r '.fields | length' "$SL/spec.json" 2>/dev/null)" \
        "$(printf '%s' "$out" | awk -F'|' '{print NF}')"

    # Spec rule 2: no field makes a network call. Every value comes from the
    # payload or from a local git command. The previous check here re-asserted
    # the project name and tested nothing, so assert the rule directly.
    net=$(grep -nE '\b(curl|wget|nc|ncat|netcat|telnet|ssh|scp|gh|http|https)\b' \
        "$SL/claude-render.sh" 2>/dev/null || true)
    check_eq 'renderer invokes no network-capable command' '' "$net"
    # Strip comments first: the renderer explains itself in prose that also
    # contains the word "git".
    gitcalls=$(sed -e 's/#.*//' "$SL/claude-render.sh" 2>/dev/null \
        | grep -oE '\bgit +(-C +"[^"]*" +)?(--[a-z-]+ +)*[a-z][a-z-]*' \
        | sed -E 's/.* //' | sort -u | tr '\n' ',')
    check_eq 'renderer uses only local git subcommands' 'rev-parse,' "$gitcalls"
fi

# Codex: the native status_line item list.
for codex_home in "$BOX_HOME/.codex" "$HOST_HOME_VIEW/.codex"; do
    cfg=$codex_home/config.toml
    label=$(printf '%s' "$codex_home" | sed "s|$HOST_HOME_VIEW|host ~|; s|$BOX_HOME|box ~|")
    if [ -f "$cfg" ]; then
        if grep -q 'status_line' "$cfg" 2>/dev/null; then
            pass "Codex status line is configured ($label/config.toml)"
        else
            fail "Codex status line is configured ($label/config.toml)" \
                 'run ~/.agents/statusline/install.sh with CODEX_HOME set to this directory'
        fi
    else
        skip "Codex status line ($label/config.toml)" 'config.toml not present'
    fi
done
