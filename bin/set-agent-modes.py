#!/usr/bin/env python3
"""Set the interactive permission defaults for the three devbox agent CLIs."""

import json
import re
import sys
from pathlib import Path


def set_toml_value(path: Path, section: str | None, key: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text().splitlines(keepends=True) if path.exists() else []
    start = 0
    end = len(lines)
    if section is not None:
        for index, line in enumerate(lines):
            if line.strip() == f"[{section}]":
                start = index + 1
                break
        else:
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += "\n"
            if lines:
                lines.append("\n")
            lines.append(f"[{section}]\n")
            start = len(lines)
        for index in range(start, len(lines)):
            if re.match(r"^\s*\[", lines[index]):
                end = index
                break
    else:
        for index, line in enumerate(lines):
            if re.match(r"^\s*\[", line):
                end = index
                break

    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    replacement = f'{key} = "{value}"\n'
    for index in range(start, end):
        if pattern.match(lines[index]):
            if lines[index] == replacement:
                return
            lines[index] = replacement
            break
    else:
        lines.insert(end, replacement)
    path.write_text("".join(lines))
    print(f"  change  {path}: {key} = {value}")


def set_claude_mode(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    current = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(current, dict):
        raise ValueError(f"{path} is not a JSON object")
    permissions = current.setdefault("permissions", {})
    if not isinstance(permissions, dict):
        raise ValueError(f"{path}: permissions is not a JSON object")
    if permissions.get("defaultMode") == "bypassPermissions" and current.get(
        "skipDangerousModePermissionPrompt"
    ) is True:
        return
    permissions["defaultMode"] = "bypassPermissions"
    current["skipDangerousModePermissionPrompt"] = True
    path.write_text(json.dumps(current, indent=2) + "\n")
    print(f"  change  {path}: bypassPermissions")


def main() -> None:
    if len(sys.argv) not in (2, 3) or (len(sys.argv) == 3 and sys.argv[2] != "--codex-only"):
        raise SystemExit("usage: set-agent-modes.py <home> [--codex-only]")
    home = Path(sys.argv[1])
    set_toml_value(home / ".codex/config.toml", None, "approval_policy", "never")
    set_toml_value(home / ".codex/config.toml", None, "sandbox_mode", "danger-full-access")
    if len(sys.argv) == 2:
        set_claude_mode(home / ".claude/settings.json")
        set_toml_value(home / ".grok/config.toml", "ui", "permission_mode", "bypassPermissions")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"set-agent-modes: {exc}") from exc
