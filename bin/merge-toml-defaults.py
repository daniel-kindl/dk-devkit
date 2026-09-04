#!/usr/bin/env python3
"""Add missing top-level keys from a defaults file into a TOML config.

    merge-toml-defaults.py <target.toml> <defaults.toml>

The script only ADDS a top-level "key = value" line that the target does not
have yet. It never changes an existing value, never touches a [table], and
never removes anything. That keeps a hand edit, and any state a client wrote
itself, intact.

It is deliberately line based: Python has no TOML writer in the standard
library, and a full re-serialisation would drop comments and reorder tables.
"""
import os
import re
import sys

KEY_RE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*=")
TABLE_RE = re.compile(r"^\s*\[")


def top_level_keys(text):
    """Keys defined before the first [table] header."""
    keys = set()
    for line in text.splitlines():
        if TABLE_RE.match(line):
            break
        m = KEY_RE.match(line)
        if m:
            keys.add(m.group(1))
    return keys


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: merge-toml-defaults.py <target.toml> <defaults.toml>")
    target, defaults = sys.argv[1], sys.argv[2]

    current = open(target).read() if os.path.exists(target) else ""
    have = top_level_keys(current)

    additions = []
    for line in open(defaults).read().splitlines():
        if TABLE_RE.match(line):
            break
        m = KEY_RE.match(line)
        if m and m.group(1) not in have:
            additions.append(line)

    if not additions:
        print(f"  ok      {target} (all defaults already present)")
        return

    # New keys go at the very TOP of the file.
    #
    # They must come before the first table header, or TOML would read them as
    # members of that table. The top is the only safe place: a block further
    # down may own the comment lines above it, and the status line installer
    # rewrites its own block from its marker comment onwards. Inserting between
    # that comment and its table would put these keys inside the block, and the
    # two writers would then undo each other on every run.
    lines = current.splitlines()
    merged = additions + ([""] + lines if lines else [])
    new = "\n".join(merged).rstrip("\n") + "\n"

    tmp = target + ".workstation.tmp"
    with open(tmp, "w") as fh:
        fh.write(new)
    os.replace(tmp, target)
    for line in additions:
        print(f"  change  {target}: added {line.strip()}")


if __name__ == "__main__":
    main()
