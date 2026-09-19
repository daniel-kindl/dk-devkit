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

# environment_path <repo-root> <ini> <host-path>
#
# The way ONE container spells a host path, read from the volume mappings its
# INI declares. Prints nothing when no mapping covers the path, which means
# that container cannot see the path at all.
#
# The INI is the source of truth, so a mount that moves does not leave a
# second copy of the mapping here.
environment_path() {
    local repo_root=$1 ini=$2 target=$3
    local line spec source dest rest
    [ -f "$repo_root/$ini" ] || return 0
    target=$(readlink -m -- "$target")
    while IFS= read -r line; do
        case $line in volume=*) ;; *) continue ;; esac
        spec=${line#volume=}
        spec=${spec%\"}
        spec=${spec#\"}
        source=${spec%%:*}
        rest=${spec#*:}
        dest=${rest%%:*}
        [ -n "$source" ] && [ -n "$dest" ] && [ "$source" != "$spec" ] || continue
        # distrobox-assemble sources the parsed values, so the INI writes
        # $HOME. Expanding it here is the same substitution, without an eval.
        source=${source//\$\{HOME\}/$HOME}
        source=${source//\$HOME/$HOME}
        source=$(readlink -m -- "$source")
        case $target in
            "$source")   printf '%s' "$dest"; return 0 ;;
            "$source"/*) printf '%s%s' "$dest" "${target#"$source"}"; return 0 ;;
        esac
    done < "$repo_root/$ini"
}

# install_environment_command <repo-root> <name>
#
# Makes bin/<name> a command inside every development environment that exists
# on this machine, so that an agent working in one types the same name a
# reader is told to type on the host.
#
# The link points at the checkout as THAT container spells it, so it is a
# dangling link when the host looks at it and a correct one inside. Each
# environment has an isolated HOME, which is why one link per environment is
# needed and why none of them is the host link.
#
# This installs a NAME, and nothing else. Every environment reaches the same
# runtime through it, because the command resolves its state from the host
# home and not from the home it was started in.
install_environment_command() {
    local repo_root=$1 name=$2
    local id status container ini packages toolchain bootstrap router inference home
    local box_home target link current

    [ -x "$repo_root/bin/$name" ] || die "bin/$name is not an executable in $repo_root"
    if ! have python3; then
        warn 'python3 is not installed; the environment modules cannot be read'
        return 0
    fi

    while IFS=$'\t' read -r id status container ini packages toolchain \
        bootstrap router inference home; do
        [ -n "$id" ] && [ "$home" != - ] && [ "$ini" != - ] || continue
        box_home=${home/#\~\//$HOME/}
        box_home=${box_home%/}
        # An environment that was never created has no home. Skip it rather
        # than make one: the next installation reaches it after it exists.
        [ -d "$box_home" ] || continue

        target=$(environment_path "$repo_root" "$ini" "$repo_root/bin/$name")
        if [ -z "$target" ]; then
            warn "$id cannot see $repo_root; $name stays a host command there"
            continue
        fi

        link=$box_home/.local/bin/$name
        current=$(readlink -- "$link" 2>/dev/null || true)
        if [ "$current" = "$target" ]; then
            ok "$id: $name"
            continue
        fi
        if [ -e "$link" ] || [ -L "$link" ]; then
            save_copy "$link"
        fi
        ensure_dir "$(dirname -- "$link")"
        run rm -f -- "$link"
        run ln -s -- "$target" "$link"
        change "$id: $name -> $target"
    done < <(environment_modules "$repo_root" supported)
}
