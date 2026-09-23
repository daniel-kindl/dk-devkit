"""Resolve command-line dependencies for the portable agentq package."""

from __future__ import annotations

import os


def executable(name: str, install_root: str, repo_root: str = "") -> str:
    """Prefer the colocated command, then search trusted absolute PATH entries.

    A target repository can contain an executable with the same name as a
    dependency. Never resolve a command from that repository or a relative
    PATH entry while the coordinator holds GitHub authority.
    """
    bundled = os.path.join(install_root, "bin", name)
    if os.access(bundled, os.X_OK):
        return bundled
    blocked_root = os.path.realpath(repo_root) if repo_root else ""

    def is_inside_repo(path: str) -> bool:
        if not blocked_root:
            return False
        try:
            return os.path.commonpath((blocked_root, path)) == blocked_root
        except ValueError:
            return False

    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not os.path.isabs(directory):
            continue
        candidate = os.path.join(directory, name)
        if not os.path.isfile(candidate) or not os.access(candidate, os.X_OK):
            continue
        if is_inside_repo(os.path.abspath(candidate)):
            continue
        resolved = os.path.realpath(candidate)
        if is_inside_repo(resolved):
            continue
        return resolved
    return bundled
