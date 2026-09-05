#!/usr/bin/env bash
#
# Report whether the Distrobox container runtime is ready.
set -euo pipefail

command -v distrobox >/dev/null 2>&1 ||
    { echo 'distrobox is not installed' >&2; exit 1; }
command -v podman >/dev/null 2>&1 || command -v docker >/dev/null 2>&1 ||
    { echo 'no container runtime is installed' >&2; exit 1; }
