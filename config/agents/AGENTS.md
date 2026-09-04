# Global agent instructions

Canonical file: `~/.agents/AGENTS.md`.
Claude Code reads it through `~/.claude/CLAUDE.md`. Codex reads it through `~/.codex/AGENTS.md`.
Both paths are symlinks to this file. Edit this file only.

Project files add to this file. A project file wins if it disagrees.

## Writing policy

Use ASD-STE100 (Simplified Technical English) as the baseline for all English
technical prose. The `asd-ste100` skill holds the rules.

### Strict mode

Use Strict mode for:

- agent-to-agent instructions
- prompts and system messages
- tool descriptions
- error messages
- status reports
- procedures
- safety-sensitive text

### STE-flavored mode

Use STE-flavored mode for:

- documentation
- code comments
- issues
- pull request descriptions and comments
- changelogs
- explanatory technical prose

### User-facing UI and product text

Write user-facing UI and product text in two steps:

1. Write the text from the ASD-STE100 baseline.
2. Apply the `humanizer` skill to get the final wording.

The final text does not have to stay strict STE. Natural wording is correct if
it improves readability and does not change the meaning.

### Never humanize

Do not apply the `humanizer` skill to:

- code identifiers
- API names and protocol names
- commands
- quoted external text
- legal text
- exact strings whose wording must not change

### Constraints on every rewrite

- Keep all facts.
- Keep the stated uncertainty. Do not make a hedged claim sound certain.
- Keep the modality. Do not change "can" to "must", or "must" to "should".
- Keep the technical meaning.
- Keep the terminology. Use one term for one concept.
- Do not invent facts. Do not add a name, number, date, quote, or citation that
  the source does not contain.

## Skills

The canonical third-party skill store is `~/.agents/skills`.
Run `sync-agent-skills` after you install a skill. The command refreshes the
per-skill Codex symlinks. It does not change the Codex native skills in
`~/.codex/skills/.system`.

## Status line

The canonical status line specification is `~/.agents/statusline/spec.json`.
The field order is:

    <model + reasoning effort> | <git branch> | PR #<n> | ctx <n>% left (<tokens> used) | 5h <n>% left | week <n>% left

Each client omits a field when the client does not supply the value.
Run `~/.agents/statusline/install.sh` to apply the specification again. The
command is idempotent. Run it after a client rewrites its own configuration.
