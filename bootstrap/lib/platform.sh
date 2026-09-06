# Platform adapter lookup for the shell half of the toolkit.
# Source this file; do not execute it. It needs bootstrap/lib/common.sh.
#
# manifests/platforms.json is the only place that holds a platform-specific
# fact. bin/toolkit-install detects the platform and answers from that
# manifest, so the shell asks the resolver instead of keeping a second copy.

# platform_hint <repo-root> <capability>
#
# Prints the one step that obtains a capability on this platform. Prints
# nothing and returns non-zero when no adapter matches, when the platform
# declares no hint, or when python3 is absent.
platform_hint() {
    local repo_root=$1 capability=$2
    have python3 || return 1
    python3 "$repo_root/bin/toolkit-install" --hint "$capability" 2>/dev/null
}
