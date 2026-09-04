#!/usr/bin/env python3
"""Add missing top-level keys from a defaults file into a JSON config.

    merge-json-defaults.py <target.json> <defaults.json>

Only keys that the target does not have yet are added. Existing values are
never changed, so hooks and a statusLine written by Orca or by the status line
installer survive untouched.
"""
import json
import os
import sys


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: merge-json-defaults.py <target.json> <defaults.json>")
    target, defaults = sys.argv[1], sys.argv[2]

    with open(defaults) as fh:
        wanted = json.load(fh)

    current = {}
    if os.path.exists(target):
        try:
            with open(target) as fh:
                current = json.load(fh)
        except json.JSONDecodeError as exc:
            sys.exit(f"  error   {target} is not valid JSON ({exc}); left unchanged")
        if not isinstance(current, dict):
            sys.exit(f"  error   {target} is not a JSON object; left unchanged")

    added = [k for k in wanted if k not in current]
    if not added:
        print(f"  ok      {target} (all defaults already present)")
        return

    for key in added:
        current[key] = wanted[key]

    tmp = target + ".workstation.tmp"
    with open(tmp, "w") as fh:
        json.dump(current, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, target)
    for key in added:
        print(f"  change  {target}: added {key}")


if __name__ == "__main__":
    main()
