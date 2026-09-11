# 8c. Agent sandbox profiles

section '8c. Agent sandbox profiles'

PROFILE_CODE=$REPO_ROOT/lib/agentqueue/sandbox.py
PY_IMAGE=$REPO_ROOT/containers/sandbox-python/Containerfile
PROFILE_DOC=$REPO_ROOT/docs/agent-sandbox-profiles.md
PROFILE_CLI=$REPO_ROOT/bin/agent-sandbox

check 'A1 profile resolver exists' -- test -f "$PROFILE_CODE"
check 'A2 Python sandbox Containerfile exists' -- test -f "$PY_IMAGE"
check 'A3 profile documentation exists' -- test -f "$PROFILE_DOC"
check 'A4 profile build command is executable' -- test -x "$PROFILE_CLI"

if command -v python3 >/dev/null 2>&1; then
    check 'B1 profile resolver compiles' -- python3 -m py_compile "$PROFILE_CODE"
    check 'B2 Python-only repositories resolve to python' -- python3 - "$REPO_ROOT" <<'PY'
import os, sys, tempfile
sys.path.insert(0, os.path.join(sys.argv[1], 'lib'))
from agentqueue import sandbox
with tempfile.TemporaryDirectory() as d:
    open(os.path.join(d, 'pyproject.toml'), 'w').close()
    assert sandbox.detect_profile(d) == 'python'
PY
    check 'B3 web repositories stay on web' -- python3 - "$REPO_ROOT" <<'PY'
import os, sys, tempfile
sys.path.insert(0, os.path.join(sys.argv[1], 'lib'))
from agentqueue import sandbox
with tempfile.TemporaryDirectory() as d:
    open(os.path.join(d, 'package.json'), 'w').close()
    assert sandbox.detect_profile(d) == 'web'
PY
    check 'B4 polyglot repositories fail conservative to web' -- python3 - "$REPO_ROOT" <<'PY'
import os, sys, tempfile
sys.path.insert(0, os.path.join(sys.argv[1], 'lib'))
from agentqueue import sandbox
with tempfile.TemporaryDirectory() as d:
    open(os.path.join(d, 'pyproject.toml'), 'w').close()
    open(os.path.join(d, 'package.json'), 'w').close()
    assert sandbox.detect_profile(d) == 'web'
PY
    check 'B5 an explicit profile wins' -- python3 - "$REPO_ROOT" <<'PY'
import os, sys, tempfile
sys.path.insert(0, os.path.join(sys.argv[1], 'lib'))
from agentqueue import sandbox
with tempfile.TemporaryDirectory() as d:
    open(os.path.join(d, 'package.json'), 'w').close()
    with open(os.path.join(d, '.agentbox-profile'), 'w') as f:
        f.write('python\n')
    assert sandbox.detect_profile(d) == 'python'
PY
    check 'B6 unknown profiles are refused' -- python3 - "$REPO_ROOT" <<'PY'
import os, sys, tempfile
sys.path.insert(0, os.path.join(sys.argv[1], 'lib'))
from agentqueue import sandbox
with tempfile.TemporaryDirectory() as d:
    with open(os.path.join(d, '.agentbox-profile'), 'w') as f:
        f.write('unknown\n')
    try:
        sandbox.detect_profile(d)
    except sandbox.SandboxProfileError:
        pass
    else:
        raise AssertionError('unknown profile was accepted')
PY
    check 'B7 Python profile resolves only to its pinned local image' -- python3 - "$REPO_ROOT" <<'PY'
import os, sys
sys.path.insert(0, os.path.join(sys.argv[1], 'lib'))
from agentqueue import sandbox
image = sandbox.image_for_profile(sys.argv[1], 'python')
assert image.startswith('localhost/workstation/sandbox-python:'), image
PY
else
    skip 'B1-B7 profile resolver tests' 'no python3 on this side'
fi

check_contains 'C1 Python sandbox carries uv' 'COPY --from=uv /uv /uvx' "$(cat "$PY_IMAGE")"
check_contains 'C2 Python version stays repository-owned' 'does not pin a Python interpreter' "$(cat "$PY_IMAGE")"
check_contains 'C3 runner passes the selected image to agentbox' 'args += ["--image", image]' "$(cat "$REPO_ROOT/lib/agentqueue/runner.py")"
check_contains 'C4 profile file cannot name an arbitrary image' '_PROFILE_KEYS' "$(cat "$PROFILE_CODE")"
