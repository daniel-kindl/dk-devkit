# The reusable android-dev Distrobox: isolation, packages, SDK and routing.

section '2l. android-dev container'

ANDROID_BOX=android-dev
ANDROID_BOX_HOME=$HOST_HOME/.local/share/distrobox-homes/android-dev

android_box_sh() {
    on_host distrobox enter -T --name "$ANDROID_BOX" -- bash -lc "$1" 2>/dev/null
}

if host_sh "podman container exists $ANDROID_BOX" >/dev/null 2>&1; then
    pass "container '$ANDROID_BOX' exists"
else
    fail "container '$ANDROID_BOX' exists" \
        'create it with: distrobox assemble create --file distrobox/android-dev.ini'
    return 0 2>/dev/null || exit 0
fi

check_eq 'android-dev image is Fedora 44' 'registry.fedoraproject.org/fedora:44' \
    "$(host_sh "podman inspect $ANDROID_BOX --format '{{.ImageName}}'" 2>/dev/null | tr -d '\r')"
check_eq 'android-dev has an isolated HOME' "$ANDROID_BOX_HOME" \
    "$(android_box_sh 'printf %s "$HOME"' 2>/dev/null)"
check 'android-dev workspace mount exists' -- android_box_sh 'test -d /workspace'

section '2m. android-dev toolchain'

android_packages=$(sed -e 's/#.*//' "$REPO_ROOT/manifests/android-dev-packages.txt" | awk 'NF')
for pkg in $android_packages; do
    check "android-dev package: $pkg" -- android_box_sh "rpm -q '$pkg' >/dev/null"
done
ini_packages=$(sed -n 's/^additional_packages=//p' "$REPO_ROOT/distrobox/android-dev.ini" |
    tr -d '"' | tr ' ' '\n' | awk 'NF' | sort | tr '\n' ' ')
check_eq 'distrobox/android-dev.ini repeats the package manifest' \
    "$(printf '%s\n' $android_packages | sort | tr '\n' ' ')" "$ini_packages"

# shellcheck source=../manifests/android-dev.env
. "$REPO_ROOT/manifests/android-dev.env"
check_eq 'android-dev uses JDK 25' '25' \
    "$(android_box_sh 'java -version 2>&1' | awk -F '\"' '/version/ {print $2}' | cut -d. -f1)"
check_contains 'ANDROID_SDK_ROOT stays in the isolated HOME' \
    "$ANDROID_BOX_HOME/$ANDROID_SDK_ROOT_REL" \
    "$(android_box_sh 'printf %s "$ANDROID_SDK_ROOT"' 2>/dev/null)"
check 'android-dev sdkmanager is available' -- \
    android_box_sh 'command -v sdkmanager >/dev/null'
check 'android-dev platform-tools are available' -- \
    android_box_sh 'command -v adb >/dev/null'
check 'android-dev API 37 platform is installed' -- \
    android_box_sh "test -d \"\$ANDROID_SDK_ROOT/platforms/$ANDROID_PLATFORM\""
check 'android-dev build tools are installed' -- \
    android_box_sh "test -d \"\$ANDROID_SDK_ROOT/build-tools/$ANDROID_BUILD_TOOLS\""
section '2n. android-dev routing and agent clients'
check 'android-dev router definition exists' -- \
    test -f "$REPO_ROOT/config/devbox-router/environments.d/android-dev.env"
for marker in settings.gradle.kts gradlew; do
    check_contains "android-dev inference includes $marker" \
        $'android-dev\t'"$marker" "$(cat "$REPO_ROOT/components/android-dev/inference.tsv")"
done
for agent in claude codex; do
    check "android-dev interactive agent is available: $agent" -- \
        android_box_sh "command -v '$agent' >/dev/null"
done
check 'android-dev shared agent policy is wired' -- \
    android_box_sh 'test -L "$HOME/.agents/AGENTS.md" && test -e "$HOME/.agents/AGENTS.md"'
check 'android-dev skill store holds the third-party skills' -- \
    android_box_sh 'ls "$HOME"/.agents/skills/*/SKILL.md >/dev/null 2>&1'
check 'android-dev Claude skills link reaches the store' -- \
    android_box_sh 'test "$HOME/.claude/skills" -ef "$HOME/.agents/skills"'
check 'no private SSH key inside android-dev HOME' -- \
    android_box_sh '! ls "$HOME"/.ssh/id_* >/dev/null 2>&1'
