# The web-dev Distrobox: existence, isolation, mounts and toolchain.

section '2. web-dev container'

if host_sh "podman container exists $BOX_NAME" >/dev/null 2>&1; then
    pass "container '$BOX_NAME' exists"
else
    fail "container '$BOX_NAME' exists" \
        'create it with: distrobox assemble create --file distrobox/web-dev.ini'
    return 0 2>/dev/null || exit 0
fi

check_eq 'image is Fedora 44' 'registry.fedoraproject.org/fedora:44' \
    "$(host_sh "podman inspect $BOX_NAME --format '{{.ImageName}}'" 2>/dev/null | tr -d '\r')"

box_home_actual=$(box_sh 'printf %s "$HOME"' 2>/dev/null)
check_eq 'isolated HOME' "$BOX_HOME" "$box_home_actual"

case $box_home_actual in
    "$HOST_HOME") fail 'HOME is isolated from the host home' 'the box shares the host HOME' ;;
    *) pass 'HOME is isolated from the host home' ;;
esac

check 'project mount: /workspace exists in the box' -- box_sh 'test -d /workspace'
check_eq 'project mount: /workspace is the host ~/projects' 'yes' \
    "$(host_sh "touch '$HOST_HOME/projects/.workstation-verify-probe' 2>/dev/null" >/dev/null 2>&1;
       box_sh 'test -e /workspace/.workstation-verify-probe && printf yes || printf no' 2>/dev/null;
       host_sh "rm -f '$HOST_HOME/projects/.workstation-verify-probe'" >/dev/null 2>&1)"

section '2b. web-dev toolchain'

# shellcheck source=../manifests/toolchain.env
. "$REPO_ROOT/manifests/toolchain.env"

check_eq "node is v$NODE_VERSION"      "v$NODE_VERSION"    "$(box_sh 'node -v' 2>/dev/null | tr -d '\r')"
check_eq "pnpm is $PNPM_VERSION"       "$PNPM_VERSION"     "$(box_sh 'pnpm -v' 2>/dev/null | tr -d '\r')"
check_eq "corepack is $COREPACK_VERSION" "$COREPACK_VERSION" "$(box_sh 'corepack -v' 2>/dev/null | tr -d '\r')"
check_eq "nvm is $NVM_VERSION"         "$NVM_VERSION"      "$(box_sh 'nvm --version' 2>/dev/null | tr -d '\r')"

check_contains 'node comes from the isolated HOME (nvm), not the host' \
    "distrobox-homes/$BOX_NAME" "$(box_sh 'command -v node' 2>/dev/null)"

for pkg in git jq gh; do
    check "web-dev package: $pkg" -- box_sh "command -v $pkg >/dev/null"
done

check_contains 'git identity is configured in the box' '@' \
    "$(box_sh 'git config --get user.email' 2>/dev/null)"

section '2c. SSH agent forwarding (no key material is printed)'

sock=$(box_sh 'printf %s "${SSH_AUTH_SOCK:-}"' 2>/dev/null)
if [ -z "$sock" ]; then
    fail 'SSH_AUTH_SOCK is visible inside the box' \
        'the host agent socket is not forwarded; git over SSH will not work in the box'
else
    pass "SSH_AUTH_SOCK is visible inside the box ($sock)"
fi

keys=$(box_sh 'ssh-add -l 2>/dev/null | grep -c "^"' 2>/dev/null || printf 0)
keys=${keys//[^0-9]/}
if [ "${keys:-0}" -ge 1 ]; then
    pass "ssh-agent holds ${keys} key(s) (fingerprints not shown)"
else
    fail 'ssh-agent holds at least one key' \
        'run on the host: ssh-add ~/.ssh/id_ed25519'
fi

check 'no private SSH key inside the container HOME' \
    -- box_sh '! ls "$HOME"/.ssh/id_* >/dev/null 2>&1'
