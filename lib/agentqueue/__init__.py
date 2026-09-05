"""agentqueue - the trusted GitHub backlog coordinator.

The workstation runs unattended agents in two halves.

    agentbox     the UNTRUSTED half. It runs model output in a disposable
                 clone inside a destroyed-afterwards Podman sandbox. It holds
                 no GitHub credential, no SSH key and no Podman socket, and it
                 stops at a validated local ``agent/*`` branch.

    agentqueue   the TRUSTED half. It reads the GitHub backlog, decides what
                 is runnable, drives agentbox, pushes the validated branch,
                 opens the pull request, waits for the checks and merges.

The split is the whole design. A sandbox cannot push, open a pull request or
merge, because it holds nothing that authenticates to GitHub. This package
holds that authority, and it never hands any part of it to a sandbox.

See docs/agentqueue.md.
"""

VERSION = "0.2.0"
