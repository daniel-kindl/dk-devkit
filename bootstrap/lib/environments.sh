# Discovery and creation of the Distrobox development environments.
# Source this file; do not execute it. It needs bootstrap/lib/common.sh.
#
# An environment is a toolkit component of kind "environment". Its module in
# components/<id>/ declares the container, the files that install it and the
# router markers it owns. Nothing here holds a list of environment names, so
# adding an environment stays one module.

# environment_modules <repo-root> [status]
#
# Prints one TSV record per environment module, ordered by identifier:
#
#   id  status  container  ini  packages  toolchain  bootstrap  router
#   inference  home
#
# An absent field is a single "-". With a status, only the modules with that
# status are printed. Read a record with:
#
#   IFS=$'\t' read -r id status container ini packages toolchain \
#       bootstrap router inference home
#
# The component installer is the one parser of the component contract, so the
# shell half never holds a second copy of it.
environment_modules() {
    local repo_root=$1 status=${2:-}
    have python3 || return 1
    python3 "$repo_root/bin/toolkit-install" --environments |
        awk -F'\t' -v want="$status" 'NR > 1 && (want == "" || $2 == want)'
}

# environment_rules <repo-root>
#
# The router inference rules of every environment module, comments removed and
# ordered by module. A planned environment contributes its markers too: the
# router then resolves the name and reports that the environment is not
# configured, which is a better answer than no answer.
environment_rules() {
    local repo_root=$1 file
    for file in "$repo_root"/components/*/inference.tsv; do
        [ -f "$file" ] || continue
        sed -e 's/#.*//' -- "$file" | awk 'NF'
    done
}

# create_development_environment <repo-root> <name>
#
# Creates the named container from distrobox/<name>.ini when it is absent.
create_development_environment() {
    local repo_root=$1 name=$2

    if ! have distrobox; then
        # One report, however many environments the caller asks for.
        if [ "${DISTROBOX_REPORTED_MISSING:-0}" != 1 ]; then
            DISTROBOX_REPORTED_MISSING=1
            warn 'distrobox is not installed'
            manual 'Install distrobox on the host, then re-run the installer'
        fi
        return 0
    fi
    if podman container exists "$name" 2>/dev/null; then
        ok "container $name already exists (left untouched)"
        return 0
    fi
    run distrobox assemble create --file "$repo_root/distrobox/$name.ini" &&
        change "created container $name"
}

# create_development_environments <repo-root>
#
# Creates the container of every supported environment module, and reports the
# in-container bootstrap each one still needs.
create_development_environments() {
    local repo_root=$1
    local id status container ini packages toolchain bootstrap router inference home

    if ! have python3; then
        warn 'python3 is not installed; the environment modules cannot be read'
        manual 'Install python3 on the host, then re-run the installer'
        return 0
    fi
    while IFS=$'\t' read -r id status container ini packages toolchain \
        bootstrap router inference home; do
        [ -n "$id" ] && [ "$container" != - ] || continue
        create_development_environment "$repo_root" "$container"
        [ "$bootstrap" != - ] || continue
        manual "Bootstrap $id: devbox exec $id --cwd $repo_root -- ./$bootstrap"
    done < <(environment_modules "$repo_root" supported)
}
