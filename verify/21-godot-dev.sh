# The reusable godot-dev Distrobox: isolation, packages, engine, routing and agents.

section '2v. godot-dev container'

GODOT_BOX=godot-dev
GODOT_BOX_HOME=$HOST_HOME/.local/share/distrobox-homes/godot-dev
GODOT_MANIFEST=$REPO_ROOT/manifests/godot-dev.env
godot_pin() { sed -n "s/^$1=//p" "$GODOT_MANIFEST" | head -1 | tr -d '\r'; }
GODOT_VERSION=$(godot_pin GODOT_VERSION)
GODOT_RELEASE=$(godot_pin GODOT_RELEASE)
GODOT_FLAVOR=$(godot_pin GODOT_FLAVOR)

godot_box_sh() {
    on_host distrobox enter -T --name "$GODOT_BOX" -- bash -lc "$1" 2>/dev/null
}

if host_sh "podman container exists $GODOT_BOX" >/dev/null 2>&1; then
    pass "container '$GODOT_BOX' exists"
else
    fail "container '$GODOT_BOX' exists" \
        'create it with: distrobox assemble create --file distrobox/godot-dev.ini'
    return 0 2>/dev/null || exit 0
fi

check_eq 'godot-dev image is Fedora 44' 'registry.fedoraproject.org/fedora:44' \
    "$(host_sh "podman inspect $GODOT_BOX --format '{{.ImageName}}'" 2>/dev/null | tr -d '\r')"
check_eq 'godot-dev has an isolated HOME' "$GODOT_BOX_HOME" \
    "$(godot_box_sh 'printf %s "$HOME"' 2>/dev/null)"
check 'godot-dev workspace mount exists' -- godot_box_sh 'test -d /workspace'

section '2w. godot-dev packages, engine and SDK'
godot_packages=$(sed -e 's/#.*//' "$REPO_ROOT/manifests/godot-dev-packages.txt" | awk 'NF')
for pkg in $godot_packages; do
    check "godot-dev package: $pkg" -- godot_box_sh "rpm -q '$pkg' >/dev/null"
done
ini_packages=$(sed -n 's/^additional_packages=//p' "$REPO_ROOT/distrobox/godot-dev.ini" |
    tr -d '"' | tr ' ' '\n' | awk 'NF' | sort | tr '\n' ' ')
check_eq 'distrobox/godot-dev.ini repeats the package manifest' \
    "$(printf '%s\n' $godot_packages | sort | tr '\n' ' ')" "$ini_packages"
for command_name in git gh jq curl unzip dotnet gcc g++ make pkg-config godot; do
    check "godot-dev command is available: $command_name" -- \
        godot_box_sh "command -v '$command_name' >/dev/null"
done
# The distribution package is feature band 1xx only, and no global.json
# rollForward policy moves down a band, so the pinned upstream SDK must be the
# command that wins. manifests/dotnet-sdk.env says why.
DOTNET_SDK_VERSION=$(sed -n 's/^DOTNET_SDK_VERSION=//p' \
    "$REPO_ROOT/manifests/dotnet-sdk.env" | head -1 | tr -d '\r')
check_eq 'godot-dev runs the pinned .NET SDK' "$DOTNET_SDK_VERSION" \
    "$(godot_box_sh 'cd "$HOME" && dotnet --version' 2>/dev/null | tr -d '\r')"
check 'the .NET SDK comes from the isolated home, not from a package' -- \
    godot_box_sh 'case "$(command -v dotnet)" in "$HOME"/*) exit 0 ;; *) exit 1 ;; esac'

# The engine must be the pinned release AND the C# build. The distribution
# package is the standard build, which cannot run C# at all.
godot_version_string=$(godot_box_sh 'godot --headless --version' 2>/dev/null | tail -1 | tr -d '\r')
check_contains "godot is the pinned release ($GODOT_VERSION.$GODOT_RELEASE)" \
    "$GODOT_VERSION.$GODOT_RELEASE" "$godot_version_string"
check_contains "godot is the C# build ($GODOT_FLAVOR)" "$GODOT_FLAVOR" "$godot_version_string"
check 'godot comes from the isolated home, not from a package' -- \
    godot_box_sh 'case "$(readlink -f "$(command -v godot)")" in "$HOME"/*) exit 0 ;; *) exit 1 ;; esac'
GODOT_ROOT_REL=$(godot_pin GODOT_ROOT_REL)
GODOT_ENGINE_DIR=$GODOT_BOX_HOME/$GODOT_ROOT_REL/$GODOT_VERSION-$GODOT_RELEASE-$GODOT_FLAVOR
check 'the C# assemblies sit beside the engine' -- \
    godot_box_sh "test -d '$GODOT_ENGINE_DIR/GodotSharp'"
# The editor builds C#, and the host application menu gives it no login shell,
# so the command is a launcher that names the pinned SDK itself.
check 'the godot command is a launcher, not a link to the engine' -- \
    godot_box_sh 'test -f "$HOME/.local/bin/godot" && ! test -L "$HOME/.local/bin/godot"'
check_contains 'the launcher names the pinned .NET SDK' \
    "$GODOT_BOX_HOME/.local/share/dotnet" \
    "$(godot_box_sh 'cat "$HOME/.local/bin/godot"' 2>/dev/null)"

section '2x. godot-dev routing and agent clients'
check 'godot-dev router definition exists' -- \
    test -f "$REPO_ROOT/config/devbox-router/environments.d/godot-dev.env"
# project.godot is the specific marker. Without the tier a Godot C# repository
# matches dotnet-dev too, and the router fails with exit 7 instead of routing.
check_contains 'godot-dev inference marks project.godot specific' \
    $'godot-dev\tproject.godot\tspecific' "$(cat "$REPO_ROOT/components/godot-dev/inference.tsv")"
check 'the router implements the specific tier' -- \
    grep -q 'best=specific' "$REPO_ROOT/bin/devbox"
for agent in claude codex grok; do
    check "godot-dev interactive agent is available: $agent" -- \
        godot_box_sh "command -v '$agent' >/dev/null"
done
check_codex_sandbox godot-dev godot_box_sh
check 'godot-dev shared agent policy is wired' -- \
    godot_box_sh 'test -L "$HOME/.agents/AGENTS.md" && test -e "$HOME/.agents/AGENTS.md"'
check 'godot-dev shared skill store exists' -- godot_box_sh 'test -d "$HOME/.agents/skills"'
check 'bootstrap/godot-dev.sh is executable' -- test -x "$REPO_ROOT/bootstrap/godot-dev.sh"
check 'godot-dev Orca bridge is executable' -- godot_box_sh 'test -x "$HOME/.local/bin/orca"'
check 'the editor has a desktop entry inside the box' -- \
    godot_box_sh 'test -f "$HOME/.local/share/applications/godot.desktop"'
GODOT_HOST_DESKTOP=$HOST_HOME/.local/share/applications/godot-dev-godot.desktop
if on_host test -f "$GODOT_HOST_DESKTOP"; then
    pass 'the host application menu has the Godot entry'
    # distrobox-enter runs the entry WITHOUT a login shell, and the PATH it
    # passes is the host one, which does not hold this container's
    # ~/.local/bin. A bare command name in the entry never resolves.
    check_contains 'the menu entry names the engine by absolute path' \
        "$GODOT_BOX_HOME/.local/bin/godot" \
        "$(on_host sed -n 's/^Exec=//p' "$GODOT_HOST_DESKTOP" 2>/dev/null | head -1)"
else
    skip 'the host application menu has the Godot entry' \
        'run bootstrap/godot-dev.sh, which exports it'
fi

section '2y. godot-dev SSH agent forwarding'
sock=$(godot_box_sh 'printf %s "${SSH_AUTH_SOCK:-}"' 2>/dev/null)
if [ -n "$sock" ]; then pass "SSH_AUTH_SOCK is visible inside godot-dev ($sock)"; else
    fail 'SSH_AUTH_SOCK is visible inside godot-dev' 'the host agent socket is not forwarded'
fi
check 'no private SSH key inside godot-dev HOME' -- godot_box_sh '! ls "$HOME"/.ssh/id_* >/dev/null 2>&1'
