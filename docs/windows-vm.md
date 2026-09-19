# The Windows virtual machine (`winbox`)

`winbox` gives this machine one Windows computer that an agent can drive. The
agent sends a `cmd.exe` command line, and gets back what the command printed
and the exit code it reported:

```console
$ winbox exec ver

Microsoft Windows [Version 10.0.26100.1]

$ winbox exec "dir C:\ && echo %COMPUTERNAME%"
$ echo $?
0
```

That is the whole contract. Everything below says how it is built, what it
costs, and where the boundaries are.

## Why a virtual machine

An agent that works on Windows code needs a Windows computer. A container
cannot supply one on Linux: a Windows program needs the Windows kernel. So
`winbox` runs a real virtual machine, with QEMU and hardware virtualisation,
and puts a command channel in front of it.

The channel is SSH, and not RDP or a web console, for one reason: an agent
needs one command, one output and one exit code. A desktop gives none of the
three.

## The commands

```bash
winbox doctor               # can this machine run the virtual machine?
winbox up --wait            # create it, and wait until it answers
winbox status               # what the container and the machine are doing
winbox exec <command...>    # ONE cmd.exe command line
winbox shell                # an interactive cmd.exe session
winbox logs --follow        # the installation progress
winbox ssh-config           # the ssh command, and a block for ~/.ssh/config
winbox stop | start | restart
winbox destroy [--disk]     # remove the container; --disk also takes the disk
```

`winbox prepare` makes the key pair, the account file and the first-boot
directory, and creates nothing else. It exists so that the setup can be proven
with no container, no image and no network, which is what `./verify.sh --only
24` does.

### What `exec` promises

The arguments are joined with one space and sent as **one** command line.
Nothing on the way interprets it: the shell on the other side is `cmd.exe`,
because the first boot set `DefaultShell` in the registry.

| Exit code | Meaning |
| --- | --- |
| 0 | the command worked |
| 2 | usage, or the machine is not configured |
| 3 | the virtual machine is not there, or does not answer |
| 255 | ssh could not connect. `cmd.exe` can also return this |
| any other | what the Windows command returned |

`winbox exec` never waits for a human. `BatchMode=yes` makes ssh report a
failure instead of asking for a password that an unattended caller cannot give.

## How it is built

```
  agent
    -> winbox exec            on the host, or inside a development container
    -> ssh 127.0.0.1:2222     key authentication only
    -> a container            dockurr/windows, which is QEMU plus an installer
    -> QEMU, with /dev/kvm
    -> Windows Server 2025
    -> cmd.exe
```

The container is an ordinary rootless Podman container. `winbox` reaches the
engine through `lib/podman-client.sh`, the same client `agentbox` uses, so the
command works from the host and from inside a development container. Distrobox
shares the host network, so `127.0.0.1:2222` is the same port on both sides.

Two host devices are needed. `/dev/kvm` is the declared capability of the
component, because without it there is no virtual machine at all.
`/dev/net/tun` is what the image builds the machine's network on; without it
the machine starts and answers no port. `winbox doctor` reports both.

### Why the guest port has to be named

Under rootless Podman the image cannot build a bridge, and it falls back to
user-mode networking. A published port then reaches the **container** and stops
there. Only a port named in `USER_PORTS` is carried the last step into Windows,
which is why `WINDOWS_VM_USER_PORTS=22` is in the manifest.

Without that line everything looks correct and nothing works: the container
runs, Windows installs, `podman ps` shows the published port, and every
connection is refused. `./verify.sh --only 24` checks the line, because the
failure gives no other signal.

## The first start

`winbox up` downloads about 5G of Microsoft installation media, and then
installs Windows with no human answering the installer. It takes between 20
minutes and an hour on a fast link. Watch it with `winbox logs --follow`, or in
a browser at `http://127.0.0.1:8006`.

At the end of the installation the machine runs
`config/windows-vm/oem/install.bat` once, with administrator rights. That file
is the whole Windows-side setup:

- it makes sure the OpenSSH server is present, and starts it at every boot
- it makes `cmd.exe` the shell an SSH command lands in
- it installs the **public** key the host staged, with the strict permissions
  that `sshd` demands of an administrator key file
- it opens port 22 in the Windows firewall
- it writes `C:\winbox-install.log`, because a first boot has no human watching
  it. Read it with `winbox exec type C:\winbox-install.log`

A second `winbox up` starts the machine that exists. Nothing is installed
again.

## Where the state lives

The **definition** is tracked here:

| Path | What it is |
| --- | --- |
| `manifests/windows-vm.env` | the image, the edition, the sizes, the ports and the timeouts |
| `config/windows-vm/oem/install.bat` | what the machine runs at its first boot |
| `bin/winbox` | the command |

The **machine** is machine-local state, outside this checkout, and no part of
it is tracked:

| Path | What it is |
| --- | --- |
| `~/.local/share/windows-vm/storage/` | the disk, which is the installed Windows |
| `~/.local/share/windows-vm/ssh/` | the key pair, mode 0600 |
| `~/.local/share/windows-vm/vm.env` | the Windows account and its password, mode 0600 |
| `~/.local/share/windows-vm/oem/` | the staged first-boot directory |

On btrfs, `winbox` turns copy-on-write off for the storage directory before
the disk is created. Windows rewrites its disk constantly, and a copy-on-write
filesystem fragments the image until it is slow. A file inherits the setting
when it is created, so this only works before the first `winbox up`, and it
does nothing to a disk that already exists.

To change the machine, change the manifest and make the machine again:

```bash
winbox destroy --disk
winbox up --wait
```

## The boundaries

**Nothing is published to the network.** Both ports are bound to `127.0.0.1`:
SSH on 2222, and the web console on 8006. The machine answers this computer and
nothing else.

**No credential is tracked.** `manifests/windows-vm.env` names the account but
holds no password. The first `winbox up` makes a 24-character password, writes
it to `~/.local/share/windows-vm/vm.env` with mode 0600, and gives that file to
Podman with `--env-file`. The value is never an argument, so it never appears
in this computer's process list. It is still in the container configuration,
where `podman inspect` shows it to the user who owns the container, which is
the user who made it.

**The private key never leaves the host.** The machine is given the public half
only, staged next to the first-boot script. `./verify.sh --only 24` runs the
real staging in a scratch directory and fails if a private key or a password
ever reaches it.

**The virtual machine is not a sandbox.** It is a computer that can reach the
network, and an agent with `winbox exec` is an administrator on it. Treat it
the way you would treat a spare Windows computer on your desk, and not the way
`agentbox` treats a disposable clone. The isolation it does give is real: a
Windows program cannot see this host's files, because no host directory is
mounted into it.

## The image, and why it is trusted

The component runs [`dockurr/windows`](https://github.com/dockur/windows), a
third-party image that wraps QEMU and answers the Windows installer from an
unattended file. It is pinned to an exact tag in the manifest, because an
unattended installation must not change behaviour because an upstream release
appeared.

The image downloads the installation media from Microsoft's servers at the
first start. Nothing else about it is trusted with anything: it gets two
devices, two published loopback ports, and two directories that this command
owns.

## The licence

The pinned edition is the **Windows Server 2025 evaluation**. It needs no
product key and runs for 180 days. It carries the OpenSSH server already, which
is why the first boot does not have to download one.

A different edition is a one-line change in `manifests/windows-vm.env`
(`WINDOWS_VM_VERSION`). A client edition such as `11` or `10` needs a licence of
your own to activate.

## What is verified

`./verify.sh --only 24` proves the definition, the credential rules and the
staging, on any platform, with no container and no network. It skips the last
check when no machine exists yet, so a fresh machine still reports a clean run.

The component is installed and verified on Bazzite. The full first
installation of Windows is a manual step, and `winbox doctor` reports whether
this machine can run it.

## When it does not answer

| What you see | What to do |
| --- | --- |
| `doctor` fails on `/dev/kvm` | turn on SVM or VT-x in the firmware setup, or join the `kvm` group |
| `doctor` fails on `/dev/net/tun` | the machine would have no network; load the `tun` module |
| `wait` times out | `winbox logs --follow`, and watch `http://127.0.0.1:8006` |
| SSH is refused after the install finished | `winbox exec` cannot help; read `C:\winbox-install.log` in the web console |
| ssh reports 255 every time | the key file permissions inside Windows are the usual cause; the first-boot script sets them, and the log says whether it ran |
