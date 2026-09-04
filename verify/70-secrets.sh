# Nothing that can hold a credential may be tracked, staged or in history.

section '7. Secrets'

if ! (cd "$REPO_ROOT" && git rev-parse --git-dir >/dev/null 2>&1); then
    skip 'secret scan of tracked files' 'not a Git repository yet'
    skip 'secret scan of the whole history' 'not a Git repository yet'
else
    check 'no secret in tracked or staged files' \
        -- env NO_COLOR=1 "$REPO_ROOT/bin/scan-secrets" --tracked
    check 'no secret anywhere in the Git history' \
        -- env NO_COLOR=1 "$REPO_ROOT/bin/scan-secrets" --history

    # Files that exist in the home directory and must never be tracked.
    forbidden=''
    for pattern in '.credentials.json' 'auth.json' 'hosts.yml' '*.sqlite' \
                   'id_ed25519' 'id_rsa' '.claude.json' 'repos.tsv' \
                   'third-party-skills.tsv' '.skill-lock.json'; do
        hits=$(cd "$REPO_ROOT" && git ls-files -- "*$pattern" 2>/dev/null | head -3)
        [ -n "$hits" ] && forbidden="$forbidden $pattern"
    done
    if [ -z "$forbidden" ]; then
        pass 'no credential or machine-state file is tracked'
    else
        fail 'no credential or machine-state file is tracked' "tracked:$forbidden"
    fi

    # The ignore rules must actually stop these paths.
    unignored=''
    for probe in .ssh/id_ed25519 .claude/.credentials.json .codex/auth.json \
                 .config/gh/hosts.yml .codex/state_5.sqlite skills/humanizer/SKILL.md \
                 config/devbox-router/repos.tsv .claude.json; do
        (cd "$REPO_ROOT" && git check-ignore -q "$probe") || unignored="$unignored $probe"
    done
    if [ -z "$unignored" ]; then
        pass '.gitignore refuses every credential and runtime-state probe path'
    else
        fail '.gitignore refuses every credential and runtime-state probe path' \
             "not ignored:$unignored"
    fi
fi

check 'docs/secrets.md documents the secret policy' -- test -f "$REPO_ROOT/docs/secrets.md"
