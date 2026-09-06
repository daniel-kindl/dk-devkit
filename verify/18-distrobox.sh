# 1e. The Distrobox container runtime that every development environment uses.
#
# This is the focused verification of the distrobox component. The component
# installs nothing: the platform supplies the runtime, and this module proves
# that the platform did. It discovers the environment modules, so that adding
# an environment stays one module.

section '1e. Distrobox container runtime'

check 'D1 the host has the distrobox command' -- \
    host_sh 'command -v distrobox >/dev/null'

RUNTIME=''
for candidate in podman docker; do
    if host_sh "command -v $candidate >/dev/null" 2>/dev/null; then
        RUNTIME=$candidate
        break
    fi
done

if [ -n "$RUNTIME" ]; then
    pass "D2 the host has a container runtime ($RUNTIME)"
    # A command can exist and still not answer. A rootless runtime needs its
    # user namespace and its storage before it can start a container.
    check "D3 the $RUNTIME runtime answers" -- host_sh "$RUNTIME info >/dev/null"
else
    fail 'D2 the host has a container runtime' \
        'neither podman nor docker is installed on the host'
    skip 'D3 the container runtime answers' 'no container runtime'
fi

# The doctor decides whether the component is ready; the verification proves
# that it converged. The two must agree, so this module runs the doctor too.
check 'D4 the component doctor agrees' -- \
    host_sh "'$HOST_REPO_ROOT/components/distrobox/doctor.sh'"

# distrobox/ is the tracked state this component owns. It holds one definition
# per supported environment module, and nothing more: a definition that no
# module declares is state that nothing installs and nothing verifies. Module
# 17 checks that a module declares its own files; this check compares the two
# sets, in both directions, and holds no environment name.
if command -v python3 >/dev/null 2>&1; then
    environments=$("$REPO_ROOT/install.sh" --environments 2>/dev/null || true)
    declared=$(printf '%s\n' "$environments" |
        awk -F'\t' '$2 == "supported" { sub(".*/", "", $4); print $4 }' | sort)
    present=$(cd "$REPO_ROOT/distrobox" && ls -1 -- *.ini 2>/dev/null | sort)
    check_eq 'D5 distrobox/ holds one definition per supported environment' \
        "$declared" "$present"

    # The definition and the module must name the same container. When they
    # differ, the installer creates one box and the router addresses another.
    while IFS=$'\t' read -r id status container ini _rest; do
        [ "$status" = supported ] || continue
        [ -f "$REPO_ROOT/$ini" ] || continue
        check_eq "D6 $ini names the $container container" "[$container]" \
            "$(sed -n '/^\[.*\]$/{p;q;}' "$REPO_ROOT/$ini")"
    done < <(printf '%s\n' "$environments" | tail -n +2)
else
    skip 'D5 distrobox/ holds one definition per supported environment' \
        'no python3 on this side'
fi
