#!/usr/bin/env bash
# Install the portable agentq package into one trusted environment.
set -euo pipefail

PACKAGE_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PREFIX=${PREFIX:-"$HOME/.local"}
TARGET="$PREFIX/lib/agentq"

if [ ! -x "$PACKAGE_ROOT/bin/agentq" ] || [ ! -d "$PACKAGE_ROOT/lib/agentqueue" ]; then
    printf 'agentq: run this installer from an extracted agentq package\n' >&2
    exit 2
fi

mkdir -p "$TARGET" "$PREFIX/bin"
for path in bin lib config manifests; do
    cp -R "$PACKAGE_ROOT/$path" "$TARGET/"
done
cp "$PACKAGE_ROOT/LICENSE" "$TARGET/LICENSE"

ln -sfn "$TARGET/bin/agentq" "$PREFIX/bin/agentq"
chmod 0755 "$TARGET/bin/agentq" "$TARGET/bin/scan-secrets" "$PREFIX/bin/agentq"
printf 'agentq: installed to %s\n' "$TARGET"
printf 'agentq: run agentq doctor from a GitHub repository\n'
