#!/usr/bin/env python3
"""Apply Codex defaults and migrate the previous toolkit policy."""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULTS = ROOT / "config/codex/config.base.toml"
MERGER = ROOT / "bin/merge-toml-defaults.py"
OLD_POLICY = {
    "approval_policy": '"on-request"',
    "sandbox_mode": '"workspace-write"',
}
NEW_POLICY = {
    "approval_policy": '"never"',
    "sandbox_mode": '"danger-full-access"',
}


def top_level_values(lines: list[str]) -> dict[str, tuple[int, str]]:
    """Return root-level key values without changing TOML table contents."""
    values: dict[str, tuple[int, str]] = {}
    for index, line in enumerate(lines):
        if re.match(r"^\s*\[", line):
            break
        match = re.match(r"^\s*([A-Za-z0-9_.-]+)\s*=\s*(.*?)\s*(?:#.*)?$", line)
        if match:
            values[match.group(1)] = (index, match.group(2))
    return values


def migrate_old_policy(path: Path) -> bool:
    """Migrate only when both root-level values match the old policy."""
    lines = path.read_text().splitlines(keepends=True) if path.exists() else []
    values = top_level_values(lines)
    if any(values.get(key, (0, ""))[1] != old for key, old in OLD_POLICY.items()):
        return False

    for key, old in OLD_POLICY.items():
        index, _ = values[key]
        newline = "\n" if lines[index].endswith("\n") else ""
        line = re.sub(
            rf"^(\s*{re.escape(key)}\s*=\s*){re.escape(old)}",
            rf"\g<1>{NEW_POLICY[key]}",
            lines[index].rstrip("\n"),
        )
        lines[index] = line + newline

    path.write_text("".join(lines))
    print(f"  change  {path}: migrated the previous Codex policy")
    return True


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: configure-codex.py <config.toml>")
    path = Path(sys.argv[1])
    path.parent.mkdir(parents=True, exist_ok=True)
    migrate_old_policy(path)
    subprocess.run(
        [sys.executable, str(MERGER), str(path), str(DEFAULTS)],
        check=True,
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"configure-codex: {exc}") from exc
