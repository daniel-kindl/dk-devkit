# 24. The Windows virtual machine an agent drives (winbox).
#
# These checks never create a container, never pull an image and never touch
# the network. They prove that the definition is present and internally
# consistent, and that the two rules this component exists to keep are in the
# code and not only in the prose:
#
#   no credential is tracked here, and no credential is ever an argument
#   the PRIVATE key never leaves the host; only the public half is staged
#
# One group is not a static check. It runs the real "winbox prepare" against a
# scratch directory, which is what a real machine would be given, and removes
# the directory again. No container and no image are involved.

section '24. Windows virtual machine (winbox)'

WV=$REPO_ROOT/bin/winbox
WV_MANIFEST=$REPO_ROOT/manifests/windows-vm.env
WV_OEM=$REPO_ROOT/config/windows-vm/oem/install.bat
WV_COMPONENT=$REPO_ROOT/components/windows-vm

# --- the pieces exist -------------------------------------------------------

check 'W1 winbox is executable'           -- test -x "$WV"
check 'W2 winbox parses'                  -- bash -n "$WV"
check 'W3 the manifest exists'            -- test -f "$WV_MANIFEST"
check 'W4 the first-boot script exists'   -- test -f "$WV_OEM"
check 'W5 the contract exists'            -- test -f "$WV_COMPONENT/component.json"
check 'W6 the component installer runs'   -- test -x "$WV_COMPONENT/install.sh"
check 'W7 the component doctor runs'      -- test -x "$WV_COMPONENT/doctor.sh"
check 'W8 winbox help answers'            -- "$WV" help

# --- the manifest is a pin, not a moving target -----------------------------

( . "$WV_MANIFEST" ) 2>/dev/null && WV_MANIFEST_OK=1 || WV_MANIFEST_OK=0
if [ "$WV_MANIFEST_OK" = 1 ]; then
    # shellcheck source=/dev/null
    . "$WV_MANIFEST"
    check_not_contains 'W9 the image tag is pinned, not "latest"' 'latest' "$WINDOWS_VM_TAG"
    check 'W10 the image tag is a version' -- \
        sh -c "case '$WINDOWS_VM_TAG' in [0-9]*) exit 0 ;; *) exit 1 ;; esac"
    check_eq 'W11 the pinned edition is Windows Server 2025' '2025' "$WINDOWS_VM_VERSION"
    # Both published ports stay on the loopback address. The machine answers
    # this computer, and nothing else on the network.
    check_eq 'W12 the ports are bound to loopback' '127.0.0.1' "$WINDOWS_VM_BIND"
    check 'W13 no password is written in the manifest' -- \
        sh -c "! grep -Eq '^[A-Z_]*PASSWORD=' '$WV_MANIFEST'"
    # The line that makes SSH reach Windows at all. Under rootless Podman the
    # image falls back to user-mode networking, where a published port reaches
    # the container and stops there. Only a port named here is carried the
    # last step into Windows, and the failure without it is silent.
    check_contains 'W13b the guest SSH port is forwarded in user-mode networking' \
        '22' "$WINDOWS_VM_USER_PORTS"
else
    for name in 'W9 the image tag is pinned, not "latest"' \
                'W10 the image tag is a version' \
                'W11 the pinned edition is Windows Server 2025' \
                'W12 the ports are bound to loopback' \
                'W13 no password is written in the manifest' \
                'W13b the guest SSH port is forwarded in user-mode networking'; do
        skip "$name" 'the manifest did not parse'
    done
fi

# --- the credential rule, in the code ---------------------------------------
#
# The generated Windows password is read by Podman from a file with mode 0600.
# Passing it as "-e PASSWORD=..." instead would publish it in the process list
# of this machine, where any other user can read it.

check 'W13c winbox passes USER_PORTS to the container' -- \
    grep -q -- '-e "USER_PORTS=\$WINDOWS_VM_USER_PORTS"' "$WV"
check 'W14 the password reaches Podman through --env-file' -- \
    grep -q -- '--env-file "\$ENV_FILE_HOST"' "$WV"
check 'W15 no password is ever a Podman argument' -- \
    sh -c "! grep -Eq -- '-e +\"?PASSWORD=' '$WV'"
check 'W16 the environment file is made with umask 077' -- \
    grep -q 'umask 077' "$WV"

# --- the engine wrapper is not called "podman" ------------------------------
#
# resolve_podman finds the client with "command -v podman", and "command -v"
# answers with the NAME of a shell function when one exists. A wrapper called
# "podman" therefore resolves to itself, and every engine call recurses
# forever and reports nothing at all. The bug is silent, so it is checked.

check 'W14b the engine wrapper is not called "podman"' -- \
    sh -c "! grep -Eq '^podman\\(\\) *\\{' '$WV'"
check 'W14c the engine wrapper exists' -- \
    grep -Eq '^engine\(\) *\{' "$WV"

# --- the first-boot script --------------------------------------------------

check 'W17 the first-boot script makes cmd.exe the SSH shell' -- \
    grep -q 'DefaultShell' "$WV_OEM"
check 'W18 the first-boot script sets the shell command option' -- \
    grep -q 'DefaultShellCommandOption' "$WV_OEM"
check 'W19 the first-boot script hardens the key file' -- \
    grep -q 'icacls' "$WV_OEM"
check 'W20 the first-boot script opens the firewall for SSH' -- \
    grep -q 'localport=22' "$WV_OEM"
check 'W21 the first-boot script holds no key material' -- \
    sh -c "! grep -q 'PRIVATE KEY' '$WV_OEM'"
check 'W22 the first-boot script is CRLF, which cmd.exe reads' -- \
    sh -c "! grep -qv \$'\\r\$' '$WV_OEM'"

# --- the staging, run for real in a scratch directory -----------------------

if command -v ssh-keygen >/dev/null 2>&1; then
    WV_SCRATCH=$(mktemp -d)
    if WINBOX_STATE_DIR=$WV_SCRATCH "$WV" prepare >/dev/null 2>&1; then
        pass 'W23 winbox prepare makes the machine state'
        check 'W24 the private key is made'   -- test -f "$WV_SCRATCH/ssh/id_ed25519"
        check 'W25 the public key is made'    -- test -f "$WV_SCRATCH/ssh/id_ed25519.pub"
        check 'W26 the account file is made'  -- test -f "$WV_SCRATCH/vm.env"
        check 'W27 the first-boot directory is staged' -- \
            test -f "$WV_SCRATCH/oem/install.bat"
        check 'W28 the public key is staged for the machine' -- \
            test -f "$WV_SCRATCH/oem/authorized_keys"

        # The rule this whole component is arranged around: what the virtual
        # machine is given can prove an identity, and cannot be one.
        check 'W29 the PRIVATE key never reaches the machine' -- \
            sh -c "! grep -rq 'PRIVATE KEY' '$WV_SCRATCH/oem'"
        check 'W30 the password never reaches the machine' -- \
            sh -c "! grep -rq 'PASSWORD' '$WV_SCRATCH/oem'"

        check_eq 'W31 the private key is readable by this user only' '600' \
            "$(stat -c '%a' "$WV_SCRATCH/ssh/id_ed25519" 2>/dev/null)"
        check_eq 'W32 the account file is readable by this user only' '600' \
            "$(stat -c '%a' "$WV_SCRATCH/vm.env" 2>/dev/null)"

        # Running it again must change nothing: an existing machine would
        # otherwise be given a key it does not know.
        WV_BEFORE=$(cat "$WV_SCRATCH/ssh/id_ed25519.pub" "$WV_SCRATCH/vm.env" 2>/dev/null)
        WINBOX_STATE_DIR=$WV_SCRATCH "$WV" prepare >/dev/null 2>&1
        WV_AFTER=$(cat "$WV_SCRATCH/ssh/id_ed25519.pub" "$WV_SCRATCH/vm.env" 2>/dev/null)
        check_eq 'W33 a second prepare keeps the same key and password' \
            "$WV_BEFORE" "$WV_AFTER"
        unset WV_BEFORE WV_AFTER
    else
        fail 'W23 winbox prepare makes the machine state' \
             "winbox prepare failed in $WV_SCRATCH"
        for name in 'W24 the private key is made' 'W25 the public key is made' \
                    'W26 the account file is made' \
                    'W27 the first-boot directory is staged' \
                    'W28 the public key is staged for the machine' \
                    'W29 the PRIVATE key never reaches the machine' \
                    'W30 the password never reaches the machine' \
                    'W31 the private key is readable by this user only' \
                    'W32 the account file is readable by this user only' \
                    'W33 a second prepare keeps the same key and password'; do
            skip "$name" 'prepare did not run'
        done
    fi
    rm -rf -- "$WV_SCRATCH"
    unset WV_SCRATCH
else
    for name in 'W23 winbox prepare makes the machine state' \
                'W24 the private key is made' 'W25 the public key is made' \
                'W26 the account file is made' \
                'W27 the first-boot directory is staged' \
                'W28 the public key is staged for the machine' \
                'W29 the PRIVATE key never reaches the machine' \
                'W30 the password never reaches the machine' \
                'W31 the private key is readable by this user only' \
                'W32 the account file is readable by this user only' \
                'W33 a second prepare keeps the same key and password'; do
        skip "$name" 'no ssh-keygen on this side'
    done
fi

# --- the machine itself, only if it is already there ------------------------
#
# Verification creates nothing. It only reports what an existing machine is
# doing, so a machine that was never created is a skip and not a failure.

if "$WV" status >/dev/null 2>&1; then
    pass 'W34 the machine answers the command channel'
else
    skip 'W34 the machine answers the command channel' \
         'no machine yet; run: winbox up --wait'
fi

unset WV WV_MANIFEST WV_OEM WV_COMPONENT WV_MANIFEST_OK
