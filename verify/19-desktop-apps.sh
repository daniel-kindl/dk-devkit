# 1f. The desktop applications the desktop-apps component installs.
#
# This is the focused verification of the desktop-apps component. It proves
# the manifest, and nothing else. The component belongs to the daniel profile,
# so a machine without Flatpak is a machine that never selected it: the module
# skips with a reason there instead of reporting a failure.

section '1f. Desktop applications'

if ! host_sh 'command -v flatpak >/dev/null' 2>/dev/null; then
    skip 'F1 every application in manifests/flatpaks.txt is installed' \
        'flatpak is not available on the host'
    return 0 2>/dev/null || exit 0
fi

# The unscoped list is the right one, and it is the same list the installation
# reads: an application that the image already provides for this user
# satisfies the manifest, whether it came from the user or the system
# installation. The installation adds a missing one with --user.
installed=$(host_sh 'flatpak list --app --columns=application' 2>/dev/null || true)
missing=''
count=0
while read -r app; do
    case ${app:-} in ''|'#'*) continue ;; esac
    count=$(( count + 1 ))
    printf '%s\n' "$installed" | grep -qxF "$app" || missing="$missing $app"
done < <(sed -e 's/#.*//' "$REPO_ROOT/manifests/flatpaks.txt" | awk 'NF')

if [ -z "$missing" ]; then
    pass "F1 every application in manifests/flatpaks.txt is installed ($count applications)"
else
    fail 'F1 every application in manifests/flatpaks.txt is installed' \
        "missing:$missing" './install.sh --components desktop-apps'
fi
