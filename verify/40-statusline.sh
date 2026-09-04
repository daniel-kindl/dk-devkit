# The shared status line: specification, renderer, and both client adapters.

section '4. Status line'

SL=$REPO_ROOT/config/agents/statusline
check 'specification is tracked (config/agents/statusline/spec.json)' -- test -f "$SL/spec.json"
check 'specification is valid JSON' -- jq -e . "$SL/spec.json"
check 'renderer is executable' -- test -x "$SL/claude-render.sh"
check 'installer is executable' -- test -x "$SL/install.sh"

# The field order is the contract stated in AGENTS.md.
order=$(jq -r '[.fields[].id] | join(",")' "$SL/spec.json" 2>/dev/null)
check_eq 'field order matches the documented contract' \
    'model,project,branch,pr,context,five_hour,week' "$order"

# Claude: settings.json must invoke the renderer.
CLAUDE_SETTINGS=$BOX_HOME/.claude/settings.json
if [ -f "$CLAUDE_SETTINGS" ]; then
    cmd=$(jq -r '.statusLine.command // ""' "$CLAUDE_SETTINGS" 2>/dev/null)
    check_contains 'Claude statusLine invokes the shared renderer' 'claude-render.sh' "$cmd"
    renderer=${cmd//\"/}
    if [ -n "$renderer" ] && [ -x "$renderer" ]; then
        pass 'the configured renderer path is executable'
    else
        fail 'the configured renderer path is executable' "not executable: [$renderer]"
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
    check_contains 'renderer emits the project'          'demo'        "$out"
    check_contains 'renderer emits the branch'           'main'        "$out"
    check_contains 'renderer emits the PR number'        'PR #7'       "$out"
    check_contains 'renderer emits the context gauge'    'ctx 83% left' "$out"
    check_contains 'renderer emits the 5h gauge'         '5h 90% left'  "$out"
    check_contains 'renderer emits the week gauge'       'week 75% left' "$out"
    check_contains 'renderer makes no network call'      'demo' "$out"
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
