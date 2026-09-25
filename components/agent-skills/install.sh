#!/usr/bin/env bash
#
# Install the default third-party agent skill profile.
#
#   components/agent-skills/install.sh [--dry-run]
#
# Skill content is never vendored into this repository. bin/install-skills
# resolves the profile and copies each selected skill from its source pack.
set -euo pipefail
REPO_ROOT=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/../.." && pwd)

exec "$REPO_ROOT/bin/install-skills" "$@"
