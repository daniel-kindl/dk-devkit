# The devbox router: installation, configuration, and resolution behaviour.
# Every check here uses DEVBOX_DRY_RUN, so nothing is executed in a container.

section '5. devbox router installation'

DEVBOX=$HOST_HOME/.local/bin/devbox

for tool in devbox devbox-verify devbox-run web-dev-run; do
    if [ "$IN_CONTAINER" = 1 ]; then
        target=$HOST_HOME_VIEW/.local/bin/$tool
    else
        target=$HOME/.local/bin/$tool
    fi
    check_link "host: ~/.local/bin/$tool -> the repository" "$target" "$REPO_ROOT/bin/$tool"
done

for tool in claude codex; do
    if on_host test -x "$HOST_HOME/.local/bin/$tool"; then
        pass "host shim: ~/.local/bin/$tool is executable"
    else
        fail "host shim: ~/.local/bin/$tool is executable" 'run bootstrap/host.sh'
    fi
done

section '5b. devbox router configuration'

if [ "$IN_CONTAINER" = 1 ]; then CFG=$HOST_HOME_VIEW/.config/devbox-router
else CFG=$HOME/.config/devbox-router; fi

check_link 'settings.env -> the repository'  "$CFG/settings.env"  "$REPO_ROOT/config/devbox-router/settings.env"

# The inference table is assembled from the environment modules, so it is a
# generated file rather than a link into the checkout.
module_rules=$(cat "$REPO_ROOT"/components/*/inference.tsv | sed -e 's/#.*//' | awk 'NF')
if [ -L "$CFG/inference.tsv" ]; then
    fail 'inference.tsv is generated from the environment modules' \
         'it is still a link into the checkout; run bootstrap/host.sh'
elif [ -f "$CFG/inference.tsv" ]; then
    check_eq 'inference.tsv holds exactly the module rules' \
        "$module_rules" "$(sed -e 's/#.*//' "$CFG/inference.tsv" | awk 'NF')"
else
    fail 'inference.tsv is installed' 'run bootstrap/host.sh'
fi

# bin/devbox carries the same rules as a heredoc, for a host that has no
# configuration file yet. The two tables must not drift apart.
builtin_rules=$(sed -n '/^builtin_rules() {/,/^RULES$/p' "$REPO_ROOT/bin/devbox" |
    sed -e '1,/^    cat <<.RULES.$/d' -e '/^RULES$/d')
check_eq 'the built-in inference rules match the environment modules' \
    "$module_rules" "$builtin_rules"

# Every supported environment module contributes its own router file.
for module in "$REPO_ROOT"/components/*/inference.tsv; do
    env_id=$(basename "$(dirname "$module")")
    router=$REPO_ROOT/config/devbox-router/environments.d/$env_id.env
    [ -f "$router" ] || continue
    check_link "environments.d/$env_id.env -> the repository" \
        "$CFG/environments.d/$env_id.env" "$router"
done

if [ -f "$CFG/repos.tsv" ]; then
    if [ -L "$CFG/repos.tsv" ]; then
        fail 'repos.tsv is local state, not a link into the repository' \
             'assignments are absolute host paths and must not be tracked'
    else
        pass 'repos.tsv is local state (a real file, not tracked)'
    fi
else
    skip 'repos.tsv' 'no assignments file yet'
fi

section '5c. Routing behaviour (dry run only)'

check 'devbox reports its version' -- on_host "$DEVBOX" version
check 'devbox check: every configured container exists' -- on_host "$DEVBOX" check

out=$(host_sh "DEVBOX_DRY_RUN=1 '$DEVBOX' exec web-dev --cwd '$HOST_HOME/projects' -- true" 2>&1)
check_contains 'explicit exec resolves to web-dev'         'env=web-dev'          "$out"
check_contains '~/projects maps to /workspace'             'guest_cwd=/workspace' "$out"

# The management fallback: outside a Git repository the agents still route.
out=$(host_sh "cd '$HOST_HOME' && DEVBOX_DRY_RUN=1 '$HOST_HOME/.local/bin/claude' --version" 2>&1)
check_contains 'claude shim outside a repository uses the default environment' 'source=default' "$out"
check_contains 'claude shim routes to web-dev'  'env=web-dev'    "$out"
check_contains 'claude shim preserves argv'     'argv[0]=claude' "$out"

out=$(host_sh "cd '$HOST_HOME' && DEVBOX_DRY_RUN=1 '$HOST_HOME/.local/bin/codex' --version" 2>&1)
check_contains 'codex shim routes to web-dev' 'env=web-dev' "$out"

# The recursion guard must hold from inside an environment.
rc=0
host_sh "DEVBOX_ACTIVE_ENV=web-dev '$HOST_HOME/.local/bin/claude' --version" >/dev/null 2>&1 || rc=$?
check_eq 'claude shim refuses to run inside an environment (exit 8)' '8' "$rc"

# Inference must resolve all five environments from repository markers.
for marker_env in "web-dev:package.json" "python-dev:pyproject.toml" "rust-dev:Cargo.toml" \
    "dotnet-dev:global.json" "android-dev:gradlew"; do
    envname=${marker_env%%:*}
    marker=${marker_env#*:}
    if printf '%s\n' "$module_rules" | grep -q "^$envname"$'\t'"$marker\$"; then
        pass "inference rule: $marker -> $envname"
    else
        fail "inference rule: $marker -> $envname" \
             "missing from components/$envname/inference.tsv"
    fi
done

check_eq 'default (management) environment is web-dev' 'web-dev' \
    "$(sed -n 's/^ *default_environment *= *//p' "$REPO_ROOT/config/devbox-router/settings.env" | tr -d ' ')"
check_eq 'Orca settings mirroring is enabled' '1' \
    "$(sed -n 's/^ *orca_integration *= *//p' "$REPO_ROOT/config/devbox-router/settings.env" | tr -d ' ')"
