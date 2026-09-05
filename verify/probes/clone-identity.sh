#!/usr/bin/env bash
#
# clone-identity.sh - prove, against a real repository and a real disposable
# clone, that agentbox gives the clone a Git identity of its own and gives the
# real repository nothing at all.
#
#   verify/probes/clone-identity.sh
#
# No container, no Podman, no model credential. It sources bin/agentbox to call
# create_clone and sanitize_clone directly, with AGENTBOX_STATE_DIR pointing at
# a scratch directory it makes and removes.
#
# The defect this holds closed: a disposable clone with no identity made
# Sandcastle propagate none into the sandbox, so the agent CLI wrote its own
# fallback identity into the clone's .git/config AFTER the orchestrator had
# recorded its integrity baseline, and an otherwise correct run was refused.

set -uo pipefail

PROBE_ROOT=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/../.." && pwd)

P_PASSED=0
P_FAILED=0
p_pass() { printf '  PASS  %s\n' "$1"; P_PASSED=$(( P_PASSED + 1 )); }
p_fail() {
    printf '  FAIL  %s\n' "$1"
    shift
    local l; for l in "$@"; do printf '        %s\n' "$l"; done
    P_FAILED=$(( P_FAILED + 1 ))
}
p_eq() {
    local name=$1 want=$2 got=$3
    [ "$want" = "$got" ] && { p_pass "$name"; return 0; }
    p_fail "$name" "expected: [$want]" "actual:   [$got]"
}

SCRATCH=$(mktemp -d -t agentbox-clone-identity-XXXXXX)
trap 'rm -rf -- "$SCRATCH"' EXIT

# The identity under test comes from the manifest, never from a copy of it.
# shellcheck source=/dev/null
. "$PROBE_ROOT/manifests/sandcastle.env"

# --- a real repository, with a local configuration worth protecting ---------
#
# It carries its own identity and its own settings. Nothing agentbox does may
# change a byte of that file.

REAL=$SCRATCH/real
mkdir -p -- "$REAL"
git -C "$REAL" init --quiet -b main
git -C "$REAL" config user.name 'A Human'
git -C "$REAL" config user.email 'human@example.invalid'
git -C "$REAL" config agentbox.probe marker
printf 'one\n' > "$REAL/a.txt"
git -C "$REAL" add a.txt
git -C "$REAL" commit --quiet -m 'first'
BASE=$(git -C "$REAL" rev-parse HEAD)

REAL_CONFIG_BEFORE=$SCRATCH/real-config.before
cp -- "$REAL/.git/config" "$REAL_CONFIG_BEFORE"

# --- drive the real create_clone -------------------------------------------
#
# "version" is the cheapest command that defines every function and returns.
# AGENTBOX_STATE_DIR keeps every path this makes inside the scratch directory.

export AGENTBOX_STATE_DIR=$SCRATCH/state
mkdir -p -- "$AGENTBOX_STATE_DIR"

OUT=$SCRATCH/out
(
    set -uo pipefail
    # shellcheck source=/dev/null
    . "$PROBE_ROOT/bin/agentbox" version >/dev/null
    KEEP_RUN_DIR=1
    BRANCH=agent/probe
    make_run_dir probe
    create_clone "$REAL" "$BASE"
    printf 'clone=%s\nrun=%s\n' "$CLONE_VIEW" "$RUN_DIR_VIEW" > "$OUT"
) >/dev/null || { printf '  FAIL  create_clone completed\n'; exit 1; }

CLONE=$(sed -n 's/^clone=//p' "$OUT")
RUN=$(sed -n 's/^run=//p' "$OUT")
[ -d "$CLONE/.git" ] || { printf '  FAIL  the disposable clone exists\n'; exit 1; }
p_pass 'create_clone made a disposable clone'

# --- 1. the clone starts with the configured agent identity -----------------

p_eq 'the clone carries the configured user.name' "$AGENTBOX_GIT_NAME" \
    "$(git -C "$CLONE" config --local --get user.name)"
p_eq 'the clone carries the configured user.email' "$AGENTBOX_GIT_EMAIL" \
    "$(git -C "$CLONE" config --local --get user.email)"

# It must be the clone's OWN configuration, not something inherited from the
# environment this probe happens to run in.
p_eq 'the identity is local to the clone' "$AGENTBOX_GIT_NAME"$'\n'"$AGENTBOX_GIT_EMAIL" \
    "$(git -C "$CLONE" config --local --list |
       sed -n -e 's/^user\.name=//p' -e 's/^user\.email=//p')"

# And it must be the identity a commit made in the clone actually gets, which
# is the whole point: the agent CLI has no reason to configure one of its own.
printf 'two\n' > "$CLONE/b.txt"
git -C "$CLONE" add b.txt >/dev/null 2>&1
git -C "$CLONE" commit --quiet -m 'a commit with no explicit identity' >/dev/null 2>&1
p_eq 'a commit in the clone is authored by the agent identity' \
    "$AGENTBOX_GIT_NAME <$AGENTBOX_GIT_EMAIL>" \
    "$(git -C "$CLONE" log -1 --format='%an <%ae>')"
p_eq 'a commit in the clone is committed by the agent identity' \
    "$AGENTBOX_GIT_NAME <$AGENTBOX_GIT_EMAIL>" \
    "$(git -C "$CLONE" log -1 --format='%cn <%ce>')"

# --- 2. the identity is recorded before anything else reads the clone -------
#
# create_clone takes the pristine copy AFTER it sets the identity. If that
# order were ever reversed, sanitize_clone would restore a configuration
# without the identity, and the host-side copy and the clone would disagree.

if grep -q "name = $AGENTBOX_GIT_NAME" "$RUN/meta/clone-config.pristine" &&
   grep -q "email = $AGENTBOX_GIT_EMAIL" "$RUN/meta/clone-config.pristine"; then
    p_pass 'the saved pristine configuration already holds the identity'
else
    p_fail 'the saved pristine configuration already holds the identity' \
        "$(tr '\n' ' ' < "$RUN/meta/clone-config.pristine")"
fi

# --- 3. the orchestrator sees the identity in its baseline ------------------
#
# This is the same module the control plane imports, called the same way.

if command -v node >/dev/null 2>&1; then
    gap=$(CLONE_DIR=$CLONE WANT_NAME=$AGENTBOX_GIT_NAME WANT_EMAIL=$AGENTBOX_GIT_EMAIL \
        node --input-type=module -e '
import { snapshotIntegrity, missingIdentity } from
  "'"$PROBE_ROOT"'/config/sandcastle/clone-integrity.mjs";
const before = snapshotIntegrity(process.env.CLONE_DIR);
process.stdout.write(
  missingIdentity(before.config, {
    name: process.env.WANT_NAME,
    email: process.env.WANT_EMAIL,
  }).join(", "),
);' 2>&1) || gap="node failed: $gap"
    p_eq 'the integrity baseline holds the identity' '' "$gap"
else
    printf '  SKIP  the integrity baseline holds the identity  (no node)\n'
fi

# --- 4. a later identity change is still restored and still visible ---------
#
# sanitize_clone must put the configuration back to the pristine copy, exactly
# as it does for an alias or a hook. Tolerating an identity change was never
# the fix.

git -C "$CLONE" config user.name 'Claude'
git -C "$CLONE" config user.email 'noreply@anthropic.com'
git -C "$CLONE" config alias.pwn '!touch /tmp/agentbox-probe-pwned'
mkdir -p -- "$CLONE/.git/hooks"
printf '#!/bin/sh\nexit 0\n' > "$CLONE/.git/hooks/post-checkout"
chmod 755 -- "$CLONE/.git/hooks/post-checkout"

(
    set -uo pipefail
    # shellcheck source=/dev/null
    . "$PROBE_ROOT/bin/agentbox" version >/dev/null
    KEEP_RUN_DIR=1
    BRANCH=agent/probe
    RUN_DIR_VIEW=$RUN
    RUN_DIR_HOST=$RUN
    CLONE_VIEW=$CLONE
    sanitize_clone
) >/dev/null && p_pass 'sanitize_clone accepted the mutated clone' ||
     p_fail 'sanitize_clone accepted the mutated clone'

p_eq 'sanitize_clone put the agent identity back' "$AGENTBOX_GIT_NAME" \
    "$(git -C "$CLONE" config --local --get user.name)"
p_eq 'sanitize_clone removed the injected alias' '' \
    "$(git -C "$CLONE" config --local --get alias.pwn 2>/dev/null)"
if [ -z "$(ls -A -- "$CLONE/.git/hooks" 2>/dev/null)" ]; then
    p_pass 'sanitize_clone removed the injected hook'
else
    p_fail 'sanitize_clone removed the injected hook' "$(ls -A -- "$CLONE/.git/hooks")"
fi

# --- 5. the real repository was never touched -------------------------------

if cmp -s -- "$REAL_CONFIG_BEFORE" "$REAL/.git/config"; then
    p_pass 'the real repository git config is unchanged, byte for byte'
else
    p_fail 'the real repository git config is unchanged, byte for byte' \
        "$(diff -- "$REAL_CONFIG_BEFORE" "$REAL/.git/config" | tr '\n' ' ')"
fi
p_eq 'the real repository kept its own identity' 'A Human' \
    "$(git -C "$REAL" config --local --get user.name)"
p_eq 'the real repository has no agent identity' 'human@example.invalid' \
    "$(git -C "$REAL" config --local --get user.email)"

printf '\npassed %d   failed %d\n' "$P_PASSED" "$P_FAILED"
[ "$P_FAILED" -eq 0 ]
