# The reusable golang-dev Distrobox: isolation, packages, Go, routing and agents.

section '2n. golang-dev container'

GO_BOX=golang-dev
GO_BOX_HOME=$HOST_HOME/.local/share/distrobox-homes/golang-dev

go_box_sh() {
    on_host distrobox enter -T --name "$GO_BOX" -- bash -lc "$1" 2>/dev/null
}

if host_sh "podman container exists $GO_BOX" >/dev/null 2>&1; then
    pass "container '$GO_BOX' exists"
else
    fail "container '$GO_BOX' exists" \
        'create it with: distrobox assemble create --file distrobox/golang-dev.ini'
    return 0 2>/dev/null || exit 0
fi

check_eq 'golang-dev image is Fedora 44' 'registry.fedoraproject.org/fedora:44' \
    "$(host_sh "podman inspect $GO_BOX --format '{{.ImageName}}'" 2>/dev/null | tr -d '\r')"
check_eq 'golang-dev has an isolated HOME' "$GO_BOX_HOME" \
    "$(go_box_sh 'printf %s "$HOME"' 2>/dev/null)"
check 'golang-dev workspace mount exists' -- go_box_sh 'test -d /workspace'

section '2o. golang-dev packages and toolchain'
go_packages=$(sed -e 's/#.*//' "$REPO_ROOT/manifests/golang-dev-packages.txt" | awk 'NF')
for pkg in $go_packages; do
    check "golang-dev package: $pkg" -- go_box_sh "rpm -q '$pkg' >/dev/null"
done
ini_packages=$(sed -n 's/^additional_packages=//p' "$REPO_ROOT/distrobox/golang-dev.ini" |
    tr -d '"' | tr ' ' '\n' | awk 'NF' | sort | tr '\n' ' ')
check_eq 'distrobox/golang-dev.ini repeats the package manifest' \
    "$(printf '%s\n' $go_packages | sort | tr '\n' ' ')" "$ini_packages"
for command_name in git gh jq curl go gcc g++ make pkg-config; do
    check "golang-dev command is available: $command_name" -- \
        go_box_sh "command -v '$command_name' >/dev/null"
done
# shellcheck source=../manifests/golang-dev.env
. "$REPO_ROOT/manifests/golang-dev.env"
check_eq 'GOPATH is inside the isolated golang-dev HOME' "$GO_BOX_HOME/$GO_PATH_REL" \
    "$(go_box_sh 'printf %s "${GOPATH:-}"' 2>/dev/null)"
check_contains 'go command comes from the container' '/usr/' \
    "$(go_box_sh 'command -v go' 2>/dev/null)"

section '2p. golang-dev routing and agent clients'
check 'golang-dev router definition exists' -- \
    test -f "$REPO_ROOT/config/devbox-router/environments.d/golang-dev.env"
for marker in go.mod go.sum go.work go.work.sum; do
    check_contains "golang-dev inference includes $marker" \
        $'golang-dev\t'"$marker" "$(cat "$REPO_ROOT/components/golang-dev/inference.tsv")"
done
for agent in claude codex; do
    check "golang-dev interactive agent is available: $agent" -- \
        go_box_sh "command -v '$agent' >/dev/null"
done
check 'golang-dev shared agent policy is wired' -- \
    go_box_sh 'test -L "$HOME/.agents/AGENTS.md" && test -e "$HOME/.agents/AGENTS.md"'
check 'golang-dev shared skill store exists' -- go_box_sh 'test -d "$HOME/.agents/skills"'
check 'bootstrap/golang-dev.sh is executable' -- test -x "$REPO_ROOT/bootstrap/golang-dev.sh"
check 'golang-dev Orca bridge is executable' -- go_box_sh 'test -x "$HOME/.local/bin/orca"'

section '2q. golang-dev SSH agent forwarding'
sock=$(go_box_sh 'printf %s "${SSH_AUTH_SOCK:-}"' 2>/dev/null)
if [ -n "$sock" ]; then pass "SSH_AUTH_SOCK is visible inside golang-dev ($sock)"; else
    fail 'SSH_AUTH_SOCK is visible inside golang-dev' 'the host agent socket is not forwarded'
fi
check 'no private SSH key inside golang-dev HOME' -- go_box_sh '! ls "$HOME"/.ssh/id_* >/dev/null 2>&1'
