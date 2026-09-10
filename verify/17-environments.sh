# 1d. The development environment modules.
#
# An environment is a component of kind "environment". Its module declares the
# container, the files that install it, and the router markers it owns. Nothing
# outside the module may hold a list of environment names.

section '1d. Development environment modules'

INSTALLER=$REPO_ROOT/install.sh

if command -v python3 >/dev/null 2>&1; then
    environments=$("$INSTALLER" --environments 2>/dev/null || true)
else
    environments=''
    skip 'E1 the environment modules are readable' 'no python3 on this side'
fi

if [ -n "$environments" ]; then
    pass 'E1 the environment modules are readable'

    # Every module declares the files it owns, and every declared file exists.
    while IFS=$'\t' read -r id status container ini packages toolchain \
        bootstrap router inference home; do
        [ -n "$id" ] || continue
        if [ "$inference" != - ] && [ -f "$REPO_ROOT/$inference" ]; then
            pass "E2 $id owns its router markers ($inference)"
        else
            fail "E2 $id owns its router markers" "missing: $inference"
        fi
        [ "$status" = supported ] || continue
        for declared in "$ini" "$packages" "$toolchain" "$bootstrap" "$router"; do
            if [ -e "$REPO_ROOT/$declared" ]; then
                pass "E3 $id declares $declared"
            else
                fail "E3 $id declares $declared" 'the declared path does not exist'
            fi
        done
    done < <(printf '%s\n' "$environments" | tail -n +2)

    # A planned module is a boundary, not an installation. Selecting one is
    # refused before anything is installed.
    for planned in $(printf '%s\n' "$environments" | awk -F'\t' '$2 == "planned" { print $1 }'); do
        check "E4 the planned $planned module cannot be installed (exit 3)" -- \
            sh -c "'$INSTALLER' --dry-run --components $planned >/dev/null 2>&1; test \$? = 3"
    done

    # The five environments the router can resolve each have a module.
    for expected in android-dev dotnet-dev golang-dev python-dev rust-dev web-dev; do
        if printf '%s\n' "$environments" | awk -F'\t' -v want="$expected" \
            '$1 == want { found = 1 } END { exit !found }'; then
            pass "E5 $expected is an environment module"
        else
            fail "E5 $expected is an environment module" \
                 "no components/$expected/component.json of kind environment"
        fi
    done
elif command -v python3 >/dev/null 2>&1; then
    fail 'E1 the environment modules are readable' 'install.sh --environments printed nothing'
fi

# The host bootstrap and the router installation discover the modules. Neither
# may name an environment, because that is the coupling this layer removes.
for shared in bootstrap/host.sh bootstrap/lib/devbox.sh; do
    # bin/web-dev-run is a compatibility wrapper, not an environment reference.
    if grep -Eq '(web|python|rust|dotnet|android)-dev([^-]|$)' "$REPO_ROOT/$shared"; then
        fail "E6 $shared names no environment" \
             'discover the modules with environment_modules instead'
    else
        pass "E6 $shared names no environment"
    fi
done

check 'E7 the host bootstrap creates every discovered environment' -- \
    grep -q 'create_development_environments "\$REPO_ROOT"' "$REPO_ROOT/bootstrap/host.sh"
check 'E8 the router installation assembles the module rules' -- \
    grep -q 'install_inference_rules' "$REPO_ROOT/bootstrap/lib/devbox.sh"
