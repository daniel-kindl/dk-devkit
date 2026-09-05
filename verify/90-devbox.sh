# The pre-existing devbox routing suite, reused verbatim.
#
# This is the only module that writes anything. It creates and removes a
# scratch directory under ~/projects and a throwaway copy of the router
# configuration. It never touches the real configuration.

section '9. devbox routing suite (bin/devbox-verify)'

if [ "$RUN_DEVBOX" != 1 ]; then
    skip 'devbox routing suite' 'disabled with --no-devbox'
    return 0 2>/dev/null || exit 0
fi

# The suite and the router come from THIS checkout when the host can reach it,
# so a branch is verified by its own code. On a bootstrapped machine the
# installed files are that same checkout, so nothing changes there. The
# installed pair is the fallback, and 50-routing.sh is what reports a machine
# whose links have drifted.
verify_bin=$HOST_HOME/.local/bin/devbox-verify
verify_env=''
if on_host test -x "$HOST_REPO_ROOT/bin/devbox-verify" &&
   on_host test -x "$HOST_REPO_ROOT/bin/devbox"; then
    verify_bin=$HOST_REPO_ROOT/bin/devbox-verify
    verify_env="DEVBOX_BIN='$HOST_REPO_ROOT/bin/devbox' "
elif ! on_host test -x "$verify_bin"; then
    fail 'devbox-verify is installed on the host' 'run bootstrap/host.sh'
    return 0 2>/dev/null || exit 0
fi

flag=''
[ "$DEVBOX_FULL" = 1 ] || flag='--fast'
printf '  %srunning %s%s %s%s\n' "$DIM" "$verify_env" "$verify_bin" "$flag" "$RESET"

out=$(host_sh "$verify_env'$verify_bin' $flag" 2>&1)
rc=$?
printf '%s\n' "$out" | sed 's/^/  | /'

dv_pass=$(printf '%s\n' "$out" | sed -n 's/^passed  *\([0-9]*\)$/\1/p'  | tail -1)
dv_fail=$(printf '%s\n' "$out" | sed -n 's/^failed  *\([0-9]*\)$/\1/p'  | tail -1)
dv_skip=$(printf '%s\n' "$out" | sed -n 's/^skipped  *\([0-9]*\)$/\1/p' | tail -1)

if [ "$rc" -eq 0 ] && [ "${dv_fail:-1}" = 0 ]; then
    pass "devbox routing suite: ${dv_pass:-?} passed, ${dv_skip:-0} skipped"
else
    fail "devbox routing suite" "exit $rc, ${dv_fail:-?} failed check(s)" \
         'see the transcript above'
fi
