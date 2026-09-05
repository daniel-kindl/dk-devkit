#!/usr/bin/env bash
#
# Install the third-party agent skills declared in manifests/skills.tsv.
#
#   components/agent-skills/install.sh [--dry-run]
#
# Skill content is never vendored into this repository. bin/install-skills
# copies it into the canonical store from each source repository.
set -euo pipefail
REPO_ROOT=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/../.." && pwd)

exec "$REPO_ROOT/bin/install-skills" "$@"
