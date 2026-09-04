# Permissions and ownership of everything this repository installs.

section '6. Permissions and ownership'

owner_ok=1
while IFS= read -r f; do
    [ -e "$f" ] || continue
    [ -O "$f" ] || { fail "tracked file is owned by this user: $f" "not owned by $(id -un)"; owner_ok=0; }
done < <(cd "$REPO_ROOT" && git ls-files 2>/dev/null | sed "s|^|$REPO_ROOT/|")
[ "$owner_ok" = 1 ] && pass 'every tracked file is owned by the current user'

ww=$(find "$REPO_ROOT" -path "$REPO_ROOT/.git" -prune -o -type f -perm -o+w -print 2>/dev/null | head -5)
if [ -z "$ww" ]; then
    pass 'no world-writable file in the checkout'
else
    fail 'no world-writable file in the checkout' "$ww"
fi

for f in bootstrap/host.sh bootstrap/web-dev.sh verify.sh \
         bin/devbox bin/devbox-verify bin/devbox-run bin/web-dev-run \
         bin/sync-agent-skills bin/install-skills bin/scan-secrets \
         config/agents/statusline/install.sh config/agents/statusline/claude-render.sh \
         config/web-dev/bin/orca-ide; do
    if [ -x "$REPO_ROOT/$f" ]; then
        pass "executable: $f"
    else
        fail "executable: $f" 'chmod 0755 it, and check core.fileMode'
    fi
done

# Private key material must stay on the host, and only readable by its owner.
if on_host test -d "$HOST_HOME/.ssh"; then
    mode=$(on_host stat -c '%a' "$HOST_HOME/.ssh" 2>/dev/null)
    case $mode in
        700) pass 'host ~/.ssh is mode 700' ;;
        *)   fail 'host ~/.ssh is mode 700' "actual mode: $mode" ;;
    esac
    bad=$(on_host bash -c "find '$HOST_HOME/.ssh' -maxdepth 1 -name 'id_*' ! -name '*.pub' ! -perm 600 -printf '%f ' 2>/dev/null" || true)
    if [ -z "$bad" ]; then
        pass 'every host private key is mode 600'
    else
        fail 'every host private key is mode 600' "wrong mode: $bad"
    fi
else
    skip 'host ~/.ssh permissions' 'no ~/.ssh on the host'
fi

# Shell syntax of everything this repository ships. The list is every tracked
# *.sh file (which covers the sourced libraries and the verification modules,
# none of which carry a shebang) plus every tracked executable whose shebang
# names a shell (bin/devbox and friends have no extension).
bad=''
count=0
while IFS= read -r f; do
    count=$(( count + 1 ))
    bash -n "$REPO_ROOT/$f" 2>/dev/null || bad="$bad $f"
done < <(cd "$REPO_ROOT" && {
             git ls-files '*.sh' 2>/dev/null
             git ls-files 'bin/*' 'config/web-dev/bin/*' verify.sh 2>/dev/null |
                 while read -r p; do
                     head -1 "$p" 2>/dev/null |
                         grep -qE '^#!.*[ /](ba)?sh$' && printf '%s\n' "$p"
                 done
         } | sort -u)
if [ -z "$bad" ]; then
    pass "every shell script in the repository parses ($count files)"
else
    fail 'every shell script in the repository parses' "syntax errors in:$bad"
fi

bad=''
while IFS= read -r f; do
    python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$REPO_ROOT/$f" 2>/dev/null ||
        bad="$bad $f"
done < <(cd "$REPO_ROOT" && git ls-files '*.py' 2>/dev/null)
if [ -z "$bad" ]; then
    pass 'every Python helper in the repository parses'
else
    fail 'every Python helper in the repository parses' "syntax errors in:$bad"
fi
