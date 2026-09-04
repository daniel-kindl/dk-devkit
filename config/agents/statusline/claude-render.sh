#!/bin/sh
# Claude Code status line renderer.
# Specification: ~/.agents/statusline/spec.json
#
# Order:
#   <model + reasoning effort> | <project> | <git branch> | PR #<n>
#   | ctx <n>% left (<tokens> used) | 5h <n>% left | week <n>% left
#
# Every value comes from the JSON payload on stdin, except the git branch,
# which comes from a local `git` call. There is no network call.
# A field with no value is dropped together with its separator.
#
# Colors use basic ANSI codes so that they stay readable on a dark theme and on
# a light theme. Set NO_COLOR to disable them.
#
# The script also forwards the payload to the Orca status line hook, if that
# hook is installed, so that the Orca integration keeps working. The forward
# runs in the background and cannot delay the render.

payload=$(cat)
[ -n "$payload" ] || exit 0

# --- forward to Orca (non-blocking, best effort) -----------------------------
orca_hook="${HOME:-}/.orca/agent-hooks/claude-statusline.sh"
if [ -n "${HOME:-}" ] && [ -r "$orca_hook" ] && [ -x "$orca_hook" ]; then
  printf '%s' "$payload" | /bin/sh "$orca_hook" >/dev/null 2>&1 &
fi

# --- render ------------------------------------------------------------------
command -v jq >/dev/null 2>&1 || exit 0

# One jq pass. Emits shell-quoted SL_* assignments.
eval "$(printf '%s' "$payload" | jq -r '
  def pct: if . == null then "" else (. | floor | tostring) end;
  def toks:
    if . == null or . <= 0 then ""
    elif . >= 1000000 then ((. / 100000 | floor) / 10 | tostring) + "M"
    elif . >= 10000   then ((. / 1000 | floor) | tostring) + "k"
    elif . >= 1000    then ((. / 100 | floor) / 10 | tostring) + "k"
    else (. | floor | tostring) end;
  def q: @sh;
  ( .model.display_name // "" ) as $m
  | ( .effort.level // "" ) as $e
  | ( (if $m == "" then "" else $m end) + (if $e == "" then "" else " " + $e end) ) as $model
  | ( .workspace.project_dir // .workspace.current_dir // "" ) as $proj
  | ( .workspace.current_dir // .cwd // "" ) as $dir
  | ( .worktree.branch // "" ) as $branch
  | ( if .pr.number == null then "" else (.pr.number|tostring) end ) as $pr
  | ( .context_window.remaining_percentage | pct ) as $ctx
  | ( ((.context_window.total_input_tokens // 0) + (.context_window.total_output_tokens // 0)) | toks ) as $used
  | ( if .rate_limits.five_hour.used_percentage == null then ""
      else ((100 - .rate_limits.five_hour.used_percentage) | pct) end ) as $fh
  | ( if .rate_limits.seven_day.used_percentage == null then ""
      else ((100 - .rate_limits.seven_day.used_percentage) | pct) end ) as $wk
  | "SL_MODEL=" + ($model|q)
  + " SL_PROJ=" + ($proj|q)
  + " SL_DIR=" + ($dir|q)
  + " SL_BRANCH=" + ($branch|q)
  + " SL_PR=" + ($pr|q)
  + " SL_CTX=" + ($ctx|q)
  + " SL_USED=" + ($used|q)
  + " SL_FH=" + ($fh|q)
  + " SL_WK=" + ($wk|q)
' 2>/dev/null)" 2>/dev/null || exit 0

# project name = last path segment
case "$SL_PROJ" in
  ''|'/') SL_PROJ='' ;;
  *) SL_PROJ=${SL_PROJ%/}; SL_PROJ=${SL_PROJ##*/} ;;
esac

# branch: payload first, then a local git call (no network)
if [ -z "$SL_BRANCH" ] && [ -n "$SL_DIR" ] && command -v git >/dev/null 2>&1; then
  SL_BRANCH=$(git -C "$SL_DIR" --no-optional-locks rev-parse --abbrev-ref HEAD 2>/dev/null) || SL_BRANCH=''
  [ "$SL_BRANCH" = "HEAD" ] && SL_BRANCH=$(git -C "$SL_DIR" --no-optional-locks rev-parse --short HEAD 2>/dev/null)
fi

# --- colors ------------------------------------------------------------------
if [ -n "${NO_COLOR:-}" ]; then
  C_RESET=''; C_DIM=''; C_MODEL=''; C_PROJ=''; C_BRANCH=''; C_PR=''
  C_GOOD=''; C_WARN=''; C_BAD=''; C_LABEL=''
else
  ESC=$(printf '\033')
  C_RESET="${ESC}[0m"
  C_DIM="${ESC}[2m"
  C_MODEL="${ESC}[1;36m"   # bold cyan
  C_PROJ="${ESC}[94m"      # bright blue
  C_BRANCH="${ESC}[35m"    # magenta
  C_PR="${ESC}[33m"        # yellow
  C_GOOD="${ESC}[32m"      # green
  C_WARN="${ESC}[33m"      # yellow
  C_BAD="${ESC}[31m"       # red
  C_LABEL="${ESC}[2m"      # dim
fi

# gauge_color <percent-left>
gauge_color() {
  case "$1" in
    ''|*[!0-9]*) printf '%s' "$C_GOOD"; return ;;
  esac
  if [ "$1" -le 15 ]; then printf '%s' "$C_BAD"
  elif [ "$1" -le 40 ]; then printf '%s' "$C_WARN"
  else printf '%s' "$C_GOOD"; fi
}

out=''
add() { [ -n "$1" ] || return 0; if [ -z "$out" ]; then out="$1"; else out="$out ${C_DIM}|${C_RESET} $1"; fi; }

[ -n "$SL_MODEL" ]  && add "${C_MODEL}${SL_MODEL}${C_RESET}"
[ -n "$SL_PROJ" ]   && add "${C_PROJ}${SL_PROJ}${C_RESET}"
[ -n "$SL_BRANCH" ] && add "${C_BRANCH}${SL_BRANCH}${C_RESET}"
[ -n "$SL_PR" ]     && add "${C_PR}PR #${SL_PR}${C_RESET}"

if [ -n "$SL_CTX" ]; then
  g=$(gauge_color "$SL_CTX")
  if [ -n "$SL_USED" ]; then
    add "${C_LABEL}ctx${C_RESET} ${g}${SL_CTX}%${C_RESET} ${C_LABEL}left (${SL_USED} used)${C_RESET}"
  else
    add "${C_LABEL}ctx${C_RESET} ${g}${SL_CTX}%${C_RESET} ${C_LABEL}left${C_RESET}"
  fi
fi
if [ -n "$SL_FH" ]; then
  g=$(gauge_color "$SL_FH")
  add "${C_LABEL}5h${C_RESET} ${g}${SL_FH}%${C_RESET} ${C_LABEL}left${C_RESET}"
fi
if [ -n "$SL_WK" ]; then
  g=$(gauge_color "$SL_WK")
  add "${C_LABEL}week${C_RESET} ${g}${SL_WK}%${C_RESET} ${C_LABEL}left${C_RESET}"
fi

[ -n "$out" ] && printf '%s\n' "$out"
exit 0
