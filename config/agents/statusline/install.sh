#!/usr/bin/env bash
# Apply the shared status line specification to Claude Code and Codex.
# Idempotent. Run it again after a client reinstalls its own configuration.
#
# Specification: ~/.agents/statusline/spec.json
#
#   install.sh                 apply to both clients
#   install.sh --claude-only   apply only the Claude Code status line
#   install.sh --codex-only    apply only the Codex status line
#
# Every path can be overridden. That is what lets one checkout configure more
# than one client home: Codex, for example, has a home on the host as well as
# one inside the container.
#
#   SPEC_DIR         directory that holds spec.json and claude-render.sh
#   CLAUDE_SETTINGS  path to the Claude Code settings.json
#   CODEX_CONFIG     path to the Codex config.toml
#   AGENT_BACKUP_DIR where the pre-change copies are kept
set -euo pipefail

SPEC_DIR="${SPEC_DIR:-$HOME/.agents/statusline}"
CLAUDE_SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
CODEX_CONFIG="${CODEX_CONFIG:-$HOME/.codex/config.toml}"
BACKUP_DIR="${AGENT_BACKUP_DIR:-$HOME/.agents/backups/$(date +%Y%m%d-%H%M%S)}"

DO_CLAUDE=1
DO_CODEX=1
case "${1:-}" in
  --claude-only) DO_CODEX=0 ;;
  --codex-only)  DO_CLAUDE=0 ;;
  "") ;;
  *) echo "install.sh: unknown option: $1" >&2; exit 2 ;;
esac

backup() { [ -f "$1" ] || return 0; mkdir -p "$BACKUP_DIR"; cp -a "$1" "$BACKUP_DIR/$(basename "$1")"; }

# --- Claude: statusLine command ---------------------------------------------
if [ "$DO_CLAUDE" = 0 ]; then
  echo "claude: skipped (--codex-only)"
elif [ -f "$CLAUDE_SETTINGS" ]; then
  backup "$CLAUDE_SETTINGS"
  python3 - "$CLAUDE_SETTINGS" "$SPEC_DIR/claude-render.sh" <<'PY'
import json, sys, os
path, renderer = sys.argv[1], sys.argv[2]
with open(path) as f:
    settings = json.load(f)
want = {"type": "command", "command": f'"{renderer}"', "padding": 0}
if settings.get("statusLine") == want:
    print("claude: status line already current")
else:
    settings["statusLine"] = want
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    print("claude: status line updated")
PY
else
  echo "claude: $CLAUDE_SETTINGS not found, skipped" >&2
fi

# --- Codex: [tui] status_line item list -------------------------------------
if [ "$DO_CODEX" = 0 ]; then
  echo "codex: skipped (--claude-only)"
else
mkdir -p "$(dirname "$CODEX_CONFIG")"
backup "$CODEX_CONFIG"
python3 - "$CODEX_CONFIG" <<'PY'
import os, re, sys
path = sys.argv[1]
block = (
    "# Shared status line. Specification: ~/.agents/statusline/spec.json\n"
    "# Order: model+effort | project | branch | PR | ctx left | tokens used | 5h left | week left\n"
    "[tui]\n"
    'status_line = [\n'
    '  "model-with-reasoning",\n'
    '  "project-name",\n'
    '  "git-branch",\n'
    '  "pull-request-number",\n'
    '  "context-remaining",\n'
    '  "used-tokens",\n'
    '  "five-hour-limit",\n'
    '  "weekly-limit",\n'
    "]\n"
    "status_line_use_colors = true\n"
)
text = open(path).read() if os.path.exists(path) else ""

# 1. Drop the block that a previous run of this script wrote. Match it exactly,
#    from its marker comment through its last line, so that a key written by
#    somebody else can never be removed with it.
marker = "# Shared status line. Specification:"
if marker in text:
    start = text.index(marker)
    m = re.compile(r"^status_line_use_colors\s*=.*$\n?", re.M).search(text, start)
    end = m.end() if m else len(text)
    text = text[:start] + text[end:]

# 2. TOML reads every key after a table header as a member of that table, so the
#    block must go AFTER the top-level keys and BEFORE the first table.
m = re.search(r"^\[", text, re.M)
preamble, tail = (text[:m.start()], text[m.start():]) if m else (text, "")

parts = []
if preamble.strip():
    parts.append(preamble.strip("\n") + "\n\n")
parts.append(block)
if tail.strip():
    parts.append("\n" + tail.lstrip("\n"))
new = "".join(parts)

if os.path.exists(path) and open(path).read() == new:
    print("codex: status line already current")
else:
    tmp = path + ".tmp"
    open(tmp, "w").write(new)
    os.replace(tmp, path)
    print("codex: status line updated")
PY
fi

echo "backups: $BACKUP_DIR"
