# The reusable python-dev Distrobox: isolation, packages, uv, routing, and agents.

section '2d. python-dev container'

PY_BOX=python-dev
PY_HOME=$HOST_HOME/.local/share/distrobox-homes/python-dev

python_box_sh() {
    on_host distrobox enter -T --name "$PY_BOX" -- bash -lc "$1" 2>/dev/null
}

if host_sh "podman container exists $PY_BOX" >/dev/null 2>&1; then
    pass "container '$PY_BOX' exists"
else
    fail "container '$PY_BOX' exists" \
        'create it with: distrobox assemble create --file distrobox/python-dev.ini'
    return 0 2>/dev/null || exit 0
fi

check_eq 'python-dev image is Fedora 44' 'registry.fedoraproject.org/fedora:44' \
    "$(host_sh "podman inspect $PY_BOX --format '{{.ImageName}}'" 2>/dev/null | tr -d '\r')"

py_home_actual=$(python_box_sh 'printf %s "$HOME"' 2>/dev/null)
check_eq 'python-dev has an isolated HOME' "$PY_HOME" "$py_home_actual"
case $py_home_actual in
    "$HOST_HOME") fail 'python-dev HOME is isolated from the host' 'the box shares the host HOME' ;;
    *) pass 'python-dev HOME is isolated from the host' ;;
esac

check 'python-dev workspace mount exists' -- python_box_sh 'test -d /workspace'

section '2e. python-dev packages and uv'

python_packages=$(sed -e 's/#.*//' "$REPO_ROOT/manifests/python-dev-packages.txt" | awk 'NF')
for pkg in $python_packages; do
    check "python-dev package: $pkg" -- python_box_sh "rpm -q '$pkg' >/dev/null"
done

ini_packages=$(sed -n 's/^additional_packages=//p' "$REPO_ROOT/distrobox/python-dev.ini" |
    tr -d '"' | tr ' ' '\n' | awk 'NF' | sort | tr '\n' ' ')
check_eq 'distrobox/python-dev.ini repeats the package manifest' \
    "$(printf '%s\n' $python_packages | sort | tr '\n' ' ')" "$ini_packages"

for command_name in git gh jq curl sqlite gcc g++ make pkg-config; do
    check "python-dev command is available: $command_name" -- \
        python_box_sh "command -v '$command_name' >/dev/null"
done

# shellcheck source=../manifests/python-dev.env
. "$REPO_ROOT/manifests/python-dev.env"
check_eq "uv is $UV_VERSION" "$UV_VERSION" \
    "$(python_box_sh 'uv --version' 2>/dev/null | awk '{print $2}' | tr -d '\r')"
check_contains 'uv comes from the isolated python-dev HOME' \
    'distrobox-homes/python-dev' "$(python_box_sh 'command -v uv' 2>/dev/null)"

if grep -Eq '^[[:space:]]*PYTHON_VERSION=' "$REPO_ROOT/manifests/python-dev.env"; then
    fail 'python-dev does not pin a project Python version' \
        'remove PYTHON_VERSION from manifests/python-dev.env'
else
    pass 'python-dev does not pin a project Python version'
fi

bootstrap_code=$(sed -E '/^[[:space:]]*#/d' "$REPO_ROOT/bootstrap/python-dev.sh")
check_not_contains 'python-dev bootstrap does not install a global project Python' \
    'uv python install' "$bootstrap_code"

section '2f. python-dev routing and agent clients'

check 'python-dev router definition exists' -- \
    test -f "$REPO_ROOT/config/devbox-router/environments.d/python-dev.env"
for marker in pyproject.toml uv.lock .python-version; do
    check_contains "python-dev inference includes $marker" \
        $'python-dev\t'"$marker" "$(cat "$REPO_ROOT/config/devbox-router/inference.tsv")"
done

# Mixed stacks are intentionally represented by more than one inference rule;
# devbox's existing ambiguity rule then refuses to guess.
check_contains 'web inference remains present for mixed Python/web repositories' \
    $'web-dev\tpackage.json' "$(cat "$REPO_ROOT/config/devbox-router/inference.tsv")"

for agent in claude codex; do
    check "python-dev interactive agent is available: $agent" -- \
        python_box_sh "command -v '$agent' >/dev/null"
done
check 'python-dev shared agent policy is wired' -- \
    python_box_sh 'test -L "$HOME/.agents/AGENTS.md" && test -e "$HOME/.agents/AGENTS.md"'
check 'python-dev shared skill store exists' -- \
    python_box_sh 'test -d "$HOME/.agents/skills"'

section '2g. python-dev SSH agent forwarding'

sock=$(python_box_sh 'printf %s "${SSH_AUTH_SOCK:-}"' 2>/dev/null)
if [ -z "$sock" ]; then
    fail 'SSH_AUTH_SOCK is visible inside python-dev' \
        'the host agent socket is not forwarded'
else
    pass "SSH_AUTH_SOCK is visible inside python-dev ($sock)"
fi

check 'no private SSH key inside python-dev HOME' -- \
    python_box_sh '! ls "$HOME"/.ssh/id_* >/dev/null 2>&1'
