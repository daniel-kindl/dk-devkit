# Shared status line

`spec.json` is the canonical specification. Both clients render the same fields
in the same order. A client drops a field when the client does not supply the
value.

    <model + reasoning effort> | <git branch> | PR #<n>
      | ctx <n>% left (<tokens> used) | 5h <n>% left | week <n>% left

## Apply it

    ~/.agents/statusline/install.sh

The command is idempotent. It backs up each file that it changes into
`~/.agents/backups/<timestamp>/`. Run it again if a client rewrites its own
configuration.

## Claude Code

Claude Code runs an arbitrary command for the status line, so `claude-render.sh`
does the rendering. The script reads the JSON payload on stdin. It takes every
value from that payload, except the git branch, which comes from a local `git`
call. There is no network call.

The script also forwards the payload to `~/.orca/agent-hooks/claude-statusline.sh`
when that hook exists. The forward keeps the Orca integration working. It runs in
the background, so it cannot delay the render.

Colors come from ANSI escape codes. Set `NO_COLOR` to remove them.

## Codex

Codex does not run an arbitrary script for the status line. It renders a fixed
list of items, set in `~/.codex/config.toml`:

    [tui]
    status_line = [...]
    status_line_use_colors = true

The item ids match the field order in `spec.json`. Codex controls the separator,
the field labels, and the colors. Codex takes the colors from the active
`/theme`.

## Limitations

- Codex prints ` · ` between fields and uses its own labels, such as
  `Context 100% left`. These are not configurable.
- Codex drops the token count when the count is zero.
- Claude Code drops the context and usage fields until the first API response of
  the session supplies them.
