"""Resolve the sandbox image for one unattended repository run.

The coordinator stays in web-dev. The repository only selects the disposable
sandbox that receives model output. An explicit ``.agentbox-profile`` file wins;
otherwise a Python-only repository is detected from its normal project files.
Everything else keeps the historical web profile.

A profile name maps only to an image pinned by ``manifests/sandcastle.env``.
A repository cannot use this mechanism to make agentq pull or run an arbitrary
image.
"""

from __future__ import annotations

import os
from typing import Dict, Tuple

from .policy import PolicyError

PROFILE_FILE = ".agentbox-profile"
DEFAULT_PROFILE = "web"

_PROFILE_KEYS = {
    "web": ("SANDBOX_IMAGE", "SANDBOX_TAG"),
    "python": ("SANDBOX_PYTHON_IMAGE", "SANDBOX_PYTHON_TAG"),
}

_PYTHON_MARKERS = ("pyproject.toml", ".python-version", "uv.lock")
_WEB_MARKERS = ("package.json", "pnpm-lock.yaml", "package-lock.json", "yarn.lock")


class SandboxProfileError(PolicyError):
    """The repository names a sandbox profile that cannot be resolved."""


def _explicit_profile(repo_root: str) -> str:
    path = os.path.join(repo_root, PROFILE_FILE)
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = [
                line.strip()
                for line in handle
                if line.strip() and not line.lstrip().startswith("#")
            ]
    except OSError as exc:
        raise SandboxProfileError(f"cannot read {path}: {exc}") from exc
    if len(lines) != 1:
        raise SandboxProfileError(
            f"{path} must contain exactly one profile name"
        )
    profile = lines[0]
    if profile not in _PROFILE_KEYS:
        raise SandboxProfileError(
            f"unknown sandbox profile {profile!r}; expected one of "
            + ", ".join(sorted(_PROFILE_KEYS))
        )
    return profile


def detect_profile(repo_root: str) -> str:
    """Return the repository sandbox profile without running any project code.

    Explicit configuration is authoritative. Auto-detection is deliberately
    conservative and backward compatible: a repository is Python only when it
    carries a Python marker and no web marker. A polyglot repository therefore
    keeps the web profile until it opts in explicitly.
    """
    explicit = _explicit_profile(repo_root)
    if explicit:
        return explicit

    has_python = any(os.path.exists(os.path.join(repo_root, name))
                     for name in _PYTHON_MARKERS)
    has_web = any(os.path.exists(os.path.join(repo_root, name))
                  for name in _WEB_MARKERS)
    if has_python and not has_web:
        return "python"
    return DEFAULT_PROFILE


def _manifest(install_root: str) -> Dict[str, str]:
    path = os.path.join(install_root, "manifests", "sandcastle.env")
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
        values[key.strip()] = value.strip()
    return values


def image_for_profile(install_root: str, profile: str) -> str:
    """Map a known profile to the exact local image reference it may use."""
    if profile not in _PROFILE_KEYS:
        raise SandboxProfileError(f"unknown sandbox profile: {profile}")
    image_key, tag_key = _PROFILE_KEYS[profile]
    values = _manifest(install_root)
    image = values.get(image_key, "")
    tag = values.get(tag_key, "")
    if not image or not tag:
        raise SandboxProfileError(
            f"sandbox profile {profile!r} is not pinned in manifests/sandcastle.env"
        )
    return f"{image}:{tag}"


def resolve(repo_root: str, install_root: str) -> Tuple[str, str]:
    """Return ``(profile, image)`` for one repository."""
    profile = detect_profile(repo_root)
    return profile, image_for_profile(install_root, profile)


def profiles() -> Tuple[str, ...]:
    """Return the profile names in stable display order."""
    return tuple(_PROFILE_KEYS)
