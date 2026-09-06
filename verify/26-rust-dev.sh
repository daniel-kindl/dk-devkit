# The reusable rust-dev Distrobox: isolation, packages, rustup, routing, and agents.

section '2h. rust-dev container'

RUST_BOX=rust-dev
RUST_BOX_HOME=$HOST_HOME/.local/share/distrobox-homes/rust-dev

rust_box_sh() {
    on_host distrobox enter -T --name "$RUST_BOX" -- bash -lc "$1" 2>/dev/null
}

if host_sh "podman container exists $RUST_BOX" >/dev/null 2>&1; then
    pass "container '$RUST_BOX' exists"
else
    fail "container '$RUST_BOX' exists" \
        'create it with: distrobox assemble create --file distrobox/rust-dev.ini'
    return 0 2>/dev/null || exit 0
fi

check_eq 'rust-dev image is Fedora 44' 'registry.fedoraproject.org/fedora:44' \
    "$(host_sh "podman inspect $RUST_BOX --format '{{.ImageName}}'" 2>/dev/null | tr -d '\r')"

rust_home_actual=$(rust_box_sh 'printf %s "$HOME"' 2>/dev/null)
check_eq 'rust-dev has an isolated HOME' "$RUST_BOX_HOME" "$rust_home_actual"
case $rust_home_actual in
    "$HOST_HOME") fail 'rust-dev HOME is isolated from the host' 'the box shares the host HOME' ;;
    *) pass 'rust-dev HOME is isolated from the host' ;;
esac

check 'rust-dev workspace mount exists' -- rust_box_sh 'test -d /workspace'

section '2i. rust-dev packages and toolchain'

rust_packages=$(sed -e 's/#.*//' "$REPO_ROOT/manifests/rust-dev-packages.txt" | awk 'NF')
for pkg in $rust_packages; do
    check "rust-dev package: $pkg" -- rust_box_sh "rpm -q '$pkg' >/dev/null"
done

ini_packages=$(sed -n 's/^additional_packages=//p' "$REPO_ROOT/distrobox/rust-dev.ini" |
    tr -d '"' | tr ' ' '\n' | awk 'NF' | sort | tr '\n' ' ')
check_eq 'distrobox/rust-dev.ini repeats the package manifest' \
    "$(printf '%s\n' $rust_packages | sort | tr '\n' ' ')" "$ini_packages"

# rustc calls the system linker, so a missing C toolchain breaks every build.
for command_name in git gh jq curl gcc g++ make pkg-config cc; do
    check "rust-dev command is available: $command_name" -- \
        rust_box_sh "command -v '$command_name' >/dev/null"
done

# shellcheck source=../manifests/rust-dev.env
. "$REPO_ROOT/manifests/rust-dev.env"
check_eq "rustc is $RUST_VERSION" "$RUST_VERSION" \
    "$(rust_box_sh 'rustc --version' 2>/dev/null | awk '{print $2}' | tr -d '\r')"
check_contains 'rustc comes from the isolated rust-dev HOME' \
    'distrobox-homes/rust-dev' "$(rust_box_sh 'command -v rustc' 2>/dev/null)"
check_contains 'cargo comes from the isolated rust-dev HOME' \
    'distrobox-homes/rust-dev' "$(rust_box_sh 'command -v cargo' 2>/dev/null)"

# rustup is what makes the pin a baseline rather than a ceiling: a repository
# with rust-toolchain.toml gets its own toolchain in this same isolated HOME.
check 'rustup manages the toolchain' -- rust_box_sh 'command -v rustup >/dev/null'
check_contains 'CARGO_HOME stays inside the isolated HOME' \
    "$RUST_BOX_HOME/$CARGO_HOME_REL" "$(rust_box_sh 'printf %s "${CARGO_HOME:-}"' 2>/dev/null)"
check_contains 'RUSTUP_HOME stays inside the isolated HOME' \
    "$RUST_BOX_HOME/$RUSTUP_HOME_REL" "$(rust_box_sh 'printf %s "${RUSTUP_HOME:-}"' 2>/dev/null)"

for component_name in ${RUST_COMPONENTS//,/ }; do
    check "rust-dev toolchain component: $component_name" -- \
        rust_box_sh "rustup component list --toolchain '$RUST_VERSION' | grep -Eq '^$component_name[^ ]* \\(installed\\)'"
done

# The environment installs no crate. A dependency belongs to a repository.
bootstrap_code=$(sed -E '/^[[:space:]]*#/d' "$REPO_ROOT/bootstrap/rust-dev.sh")
check_not_contains 'rust-dev bootstrap installs no crate globally' \
    'cargo install' "$bootstrap_code"

section '2j. rust-dev routing and agent clients'

check 'rust-dev router definition exists' -- \
    test -f "$REPO_ROOT/config/devbox-router/environments.d/rust-dev.env"
# The environment owns its markers; the installer assembles them.
for marker in Cargo.toml Cargo.lock rust-toolchain.toml; do
    check_contains "rust-dev inference includes $marker" \
        $'rust-dev\t'"$marker" "$(cat "$REPO_ROOT/components/rust-dev/inference.tsv")"
done

for agent in claude codex; do
    check "rust-dev interactive agent is available: $agent" -- \
        rust_box_sh "command -v '$agent' >/dev/null"
done
check 'rust-dev shared agent policy is wired' -- \
    rust_box_sh 'test -L "$HOME/.agents/AGENTS.md" && test -e "$HOME/.agents/AGENTS.md"'
check 'rust-dev shared skill store exists' -- \
    rust_box_sh 'test -d "$HOME/.agents/skills"'

# Both files are run directly, so a lost executable bit breaks the documented
# bootstrap command and the Orca bridge.
check 'bootstrap/rust-dev.sh is executable' -- test -x "$REPO_ROOT/bootstrap/rust-dev.sh"
check 'rust-dev Orca bridge is executable' -- \
    rust_box_sh 'test -x "$HOME/.local/bin/orca"'

section '2k. rust-dev SSH agent forwarding'

sock=$(rust_box_sh 'printf %s "${SSH_AUTH_SOCK:-}"' 2>/dev/null)
if [ -z "$sock" ]; then
    fail 'SSH_AUTH_SOCK is visible inside rust-dev' \
        'the host agent socket is not forwarded'
else
    pass "SSH_AUTH_SOCK is visible inside rust-dev ($sock)"
fi

check 'no private SSH key inside rust-dev HOME' -- \
    rust_box_sh '! ls "$HOME"/.ssh/id_* >/dev/null 2>&1'
