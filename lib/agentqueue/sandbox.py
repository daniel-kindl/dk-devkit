"""Resolve the sandbox image for one unattended repository run.

The coordinator stays in web-dev. The repository only selects the disposable
sandbox that receives model output. An explicit ``.agentbox-profile`` file wins;
otherwise a Python-only repository is detected from its normal project files.
Everything else keeps the historical web profile.

A profile name maps only to a local image pinned by ``manifests/sandcastle.env``.
A repository cannot use this mechanism to make agentq pull or run an arbitrary
image.
"""

from __future__ import annotations

import os
import stat
from typing import Dict, Tuple

from .policy import PolicyError

PROFILE_FILE = ".agentbox-profile"
DEFAULT_PROFILE = "web"
MANIFEST = os.path.join("manifests", "sandcastle.env")

# The profile file holds one short name. A larger file is not a profile file.
_PROFILE_FILE_LIMIT = 256

# A Python marker counts only at the repository root.
_PYTHON_MARKERS = ("pyproject.toml", ".python-version", "uv.lock")

# The project files of every other toolchain. One of them anywhere in the tree
# keeps the repository on the default profile.
_OTHER_MARKERS = frozenset((
    "package.json", "pnpm-lock.yaml", "package-lock.json", "yarn.lock",
    "bun.lock", "bun.lockb", "deno.json", "deno.jsonc", "tsconfig.json",
    "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts",
    "Gemfile", "composer.json", "mix.exs",
))
_OTHER_SUFFIXES = (".csproj", ".fsproj", ".sln")

# Directories that hold installed or generated files, not project files. A
# directory whose name starts with "." is skipped too.
_SKIP_DIRS = frozenset(("node_modules", "__pycache__", "venv", "site-packages"))

# Detection reads at most this many directory entries. A larger tree keeps the
# default profile, because detection must stay cheap and conservative.
_WALK_LIMIT = 50000


class SandboxProfileError(PolicyError):
    """The repository names a sandbox profile that cannot be resolved."""


def _manifest(install_root: str) -> Dict[str, str]:
    path = os.path.join(install_root, MANIFEST)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = tuple(handle)
    except OSError as exc:
        raise SandboxProfileError(f"cannot read {path}: {exc}") from exc

    values: Dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        # The shell sources this file, so a quoted value means the same
        # value without its quotes.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_profiles(install_root: str) -> Dict[str, str]:
    """Return every profile name and its image, in manifest order.

    ``SANDBOX_PROFILES`` lists ``<name>:<prefix>`` entries, and a profile's
    image is ``<prefix>_IMAGE:<prefix>_TAG``. The image must be local.
    """
    values = _manifest(install_root)
    entries = values.get("SANDBOX_PROFILES", "").split()
    if not entries:
        raise SandboxProfileError(f"SANDBOX_PROFILES is not set in {MANIFEST}")
    profiles: Dict[str, str] = {}
    for entry in entries:
        name, sep, prefix = entry.partition(":")
        if not sep or not name or not prefix:
            raise SandboxProfileError(
                f"SANDBOX_PROFILES in {MANIFEST} has a malformed entry: {entry}"
            )
        image = values.get(f"{prefix}_IMAGE", "")
        tag = values.get(f"{prefix}_TAG", "")
        if not image or not tag:
            raise SandboxProfileError(
                f"sandbox profile {name} is not pinned in {MANIFEST}"
            )
        if not image.startswith("localhost/"):
            raise SandboxProfileError(
                f"sandbox profile {name} must name a localhost/ image in {MANIFEST}"
            )
        profiles[name] = f"{image}:{tag}"
    if DEFAULT_PROFILE not in profiles:
        raise SandboxProfileError(
            f"SANDBOX_PROFILES in {MANIFEST} must include {DEFAULT_PROFILE}"
        )
    return profiles


def _explicit_profile(repo_root: str, known: Tuple[str, ...]) -> str:
    path = os.path.join(repo_root, PROFILE_FILE)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return ""
    except OSError as exc:
        raise SandboxProfileError(
            f"cannot read {PROFILE_FILE}: {exc.strerror}"
        ) from exc
    # A tracked symbolic link can point at any file on the trusted side. Only a
    # regular file is read, so no other file can reach an error message.
    if not stat.S_ISREG(info.st_mode):
        raise SandboxProfileError(
            f"{PROFILE_FILE} must be a regular file. A symbolic link is not permitted."
        )
    if info.st_size > _PROFILE_FILE_LIMIT:
        raise SandboxProfileError(
            f"{PROFILE_FILE} must not be larger than {_PROFILE_FILE_LIMIT} bytes"
        )
    try:
        # O_NOFOLLOW closes the gap between the lstat and the open.
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as handle:
            data = handle.read(_PROFILE_FILE_LIMIT + 1)
    except OSError as exc:
        raise SandboxProfileError(
            f"cannot read {PROFILE_FILE}: {exc.strerror}"
        ) from exc
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SandboxProfileError(f"{PROFILE_FILE} must be UTF-8 text") from exc
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if len(lines) != 1:
        raise SandboxProfileError(
            f"{PROFILE_FILE} must contain exactly one profile name"
        )
    profile = lines[0]
    if profile not in known:
        # The value is not repeated here, because the repository wrote it.
        raise SandboxProfileError(
            f"{PROFILE_FILE} names an unknown sandbox profile. Use one of: "
            + ", ".join(known)
        )
    return profile


def _has_other_toolchain(repo_root: str) -> bool:
    """Return True when the tree holds a project file of a non-Python toolchain."""
    seen = 0
    for _current, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in _SKIP_DIRS]
        seen += len(dirs) + len(files)
        if seen > _WALK_LIMIT:
            return True
        for name in files:
            if name in _OTHER_MARKERS or name.endswith(_OTHER_SUFFIXES):
                return True
    return False


def detect_profile(repo_root: str, known: Tuple[str, ...]) -> str:
    """Return the repository sandbox profile without running any project code.

    Explicit configuration is authoritative. Auto-detection is deliberately
    conservative and backward compatible: a repository is Python only when its
    root carries a Python marker and no directory carries a project file of
    another toolchain. A polyglot repository keeps the web profile until it
    opts in explicitly.
    """
    explicit = _explicit_profile(repo_root, known)
    if explicit:
        return explicit

    has_python = any(os.path.isfile(os.path.join(repo_root, name))
                     for name in _PYTHON_MARKERS)
    if has_python and "python" in known and not _has_other_toolchain(repo_root):
        return "python"
    return DEFAULT_PROFILE


def resolve(repo_root: str, install_root: str) -> Tuple[str, str]:
    """Return ``(profile, image)`` for one repository."""
    profiles = load_profiles(install_root)
    profile = detect_profile(repo_root, tuple(profiles))
    return profile, profiles[profile]
