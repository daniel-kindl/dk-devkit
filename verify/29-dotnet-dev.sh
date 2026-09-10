# The reusable dotnet-dev Distrobox: isolation, packages, SDK, routing and agents.

section '2r. dotnet-dev container'

DOTNET_BOX=dotnet-dev
DOTNET_BOX_HOME=$HOST_HOME/.local/share/distrobox-homes/dotnet-dev

dotnet_box_sh() {
    on_host distrobox enter -T --name "$DOTNET_BOX" -- bash -lc "$1" 2>/dev/null
}

if host_sh "podman container exists $DOTNET_BOX" >/dev/null 2>&1; then
    pass "container '$DOTNET_BOX' exists"
else
    fail "container '$DOTNET_BOX' exists" \
        'create it with: distrobox assemble create --file distrobox/dotnet-dev.ini'
    return 0 2>/dev/null || exit 0
fi

check_eq 'dotnet-dev image is Fedora 44' 'registry.fedoraproject.org/fedora:44' \
    "$(host_sh "podman inspect $DOTNET_BOX --format '{{.ImageName}}'" 2>/dev/null | tr -d '\r')"
check_eq 'dotnet-dev has an isolated HOME' "$DOTNET_BOX_HOME" \
    "$(dotnet_box_sh 'printf %s "$HOME"' 2>/dev/null)"
check 'dotnet-dev workspace mount exists' -- dotnet_box_sh 'test -d /workspace'

section '2s. dotnet-dev packages and SDK'
dotnet_packages=$(sed -e 's/#.*//' "$REPO_ROOT/manifests/dotnet-dev-packages.txt" | awk 'NF')
for pkg in $dotnet_packages; do
    check "dotnet-dev package: $pkg" -- dotnet_box_sh "rpm -q '$pkg' >/dev/null"
done
ini_packages=$(sed -n 's/^additional_packages=//p' "$REPO_ROOT/distrobox/dotnet-dev.ini" |
    tr -d '"' | tr ' ' '\n' | awk 'NF' | sort | tr '\n' ' ')
check_eq 'distrobox/dotnet-dev.ini repeats the package manifest' \
    "$(printf '%s\n' $dotnet_packages | sort | tr '\n' ' ')" "$ini_packages"
for command_name in git gh jq curl dotnet gcc g++ make pkg-config; do
    check "dotnet-dev command is available: $command_name" -- \
        dotnet_box_sh "command -v '$command_name' >/dev/null"
done
check_contains '.NET SDK command comes from the container' '/usr/' \
    "$(dotnet_box_sh 'command -v dotnet' 2>/dev/null)"

section '2t. dotnet-dev routing and agent clients'
check 'dotnet-dev router definition exists' -- \
    test -f "$REPO_ROOT/config/devbox-router/environments.d/dotnet-dev.env"
for marker in '*.sln' '*.slnx' '*.csproj' '*.fsproj' global.json; do
    check_contains "dotnet-dev inference includes $marker" \
        $'dotnet-dev\t'"$marker" "$(cat "$REPO_ROOT/components/dotnet-dev/inference.tsv")"
done
for agent in claude codex; do
    check "dotnet-dev interactive agent is available: $agent" -- \
        dotnet_box_sh "command -v '$agent' >/dev/null"
done
check 'dotnet-dev shared agent policy is wired' -- \
    dotnet_box_sh 'test -L "$HOME/.agents/AGENTS.md" && test -e "$HOME/.agents/AGENTS.md"'
check 'dotnet-dev shared skill store exists' -- dotnet_box_sh 'test -d "$HOME/.agents/skills"'
check 'bootstrap/dotnet-dev.sh is executable' -- test -x "$REPO_ROOT/bootstrap/dotnet-dev.sh"
check 'dotnet-dev Orca bridge is executable' -- dotnet_box_sh 'test -x "$HOME/.local/bin/orca"'

section '2u. dotnet-dev SSH agent forwarding'
sock=$(dotnet_box_sh 'printf %s "${SSH_AUTH_SOCK:-}"' 2>/dev/null)
if [ -n "$sock" ]; then pass "SSH_AUTH_SOCK is visible inside dotnet-dev ($sock)"; else
    fail 'SSH_AUTH_SOCK is visible inside dotnet-dev' 'the host agent socket is not forwarded'
fi
check 'no private SSH key inside dotnet-dev HOME' -- dotnet_box_sh '! ls "$HOME"/.ssh/id_* >/dev/null 2>&1'
