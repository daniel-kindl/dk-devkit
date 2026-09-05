"""Internal implementation package for agentq, the trusted GitHub backlog coordinator.

The workstation runs unattended agents in two halves.

    agentbox     the UNTRUSTED half. It runs model output in a disposable
                 clone inside a destroyed-afterwards Podman sandbox. It holds
                 no GitHub credential, no SSH key and no Podman socket, and it
                 stops at a validated local ``agent/*`` branch.

    agentq       the TRUSTED half. It reads the GitHub backlog, decides what
                 is runnable, drives agentbox, pushes the validated branch,
                 opens the pull request, waits for the checks and merges.

The Python package name remains ``agentqueue`` for now as an internal durable
identifier. The supported CLI and human-facing product name are ``agentq``.
The split is the whole design: a sandbox cannot push, open a pull request or
merge because it holds nothing that authenticates to GitHub.
"""

VERSION = "0.3.0"
