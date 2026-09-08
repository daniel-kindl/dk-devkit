# rust-dev

`rust-dev` is the reusable Rust development environment. It is not tied to a single repository.

## Boundary

The container provides the development capability:

- Fedora 44;
- isolated HOME at `~/.local/share/distrobox-homes/rust-dev`;
- host `~/projects` mounted at `/workspace`;
- Git/GitHub tooling;
- the C toolchain that `rustc` needs to link;
- `rustup`, with a pinned baseline toolchain, `rustfmt` and `clippy`;
- Claude Code and Codex for interactive development;
- the shared agent policy, skills, status line, and Orca bridge.

A project provides its own toolchain and application state:

- the toolchain pin (`rust-toolchain.toml`);
- `Cargo.toml`;
- `Cargo.lock`;
- `target/`;
- application and test dependencies.

Do not add Tokio, Serde, Axum, Diesel, or another crate to the container. A crate is a project dependency, and `cargo` resolves it per repository. A developer tool such as `cargo-nextest` is the same: install it in the container with `cargo install`, and do not put it in the manifest until evidence shows every Rust project here needs it.

## Create and bootstrap

The host bootstrap creates the container when it is absent and registers the router definition:

```bash
./bootstrap/host.sh
```

Or install only this environment and what it needs:

```bash
./install.sh --components rust-dev
```

Either path ends in the same in-container bootstrap:

```bash
devbox exec rust-dev --cwd ~/projects/dk-devkit -- ./bootstrap/rust-dev.sh
```

Authentication is manual per isolated HOME:

```bash
devbox exec rust-dev -- gh auth login --git-protocol ssh --skip-ssh-key
devbox exec rust-dev -- claude
devbox exec rust-dev -- codex login
```

The SSH private key is not copied into the container. Distrobox exposes the host ssh-agent socket instead, which is why `gh` needs `--skip-ssh-key`: without the flag, the login prompt generates a second key inside the isolated HOME and uploads it to GitHub.

## Toolchain ownership

`manifests/rust-dev.env` pins `RUST_VERSION`, but that pin is a **baseline**, not a ceiling. It is the toolchain a repository gets when it asks for nothing.

A project can pin its own toolchain:

```toml
# rust-toolchain.toml
[toolchain]
channel = "1.98.1"
components = ["rustfmt", "clippy"]
```

`rustup` then installs that toolchain into the isolated `rust-dev` HOME on first use, and every `cargo` call in that repository uses it. This is the same split that `python-dev` makes with `uv`: the container owns the toolchain manager, and the repository owns the toolchain.

`CARGO_HOME` and `RUSTUP_HOME` stay inside the container HOME, so the registry cache, the installed toolchains and the binaries from `cargo install` never reach the host or another environment.

## Routing

The router knows these Rust markers:

```text
Cargo.toml
Cargo.lock
rust-toolchain.toml
```

When exactly one environment family matches, `devbox` can infer `rust-dev`. A repository can always make the choice explicit with a tracked `.devbox` file containing:

```text
rust-dev
```

If a repository matches Rust and another environment at the same time, such as `Cargo.toml` plus `package.json`, automatic inference remains ambiguous and `devbox` refuses to guess. Add an explicit repository declaration when that is intentional.

## Verification

After bootstrap:

```bash
./verify.sh --only 26
```

The focused module checks the container image and HOME boundary, package-manifest parity, the linker baseline, the `rustc` version and where it comes from, the `CARGO_HOME`/`RUSTUP_HOME` boundary, the toolchain components, routing declarations, interactive agent clients, shared agent wiring, and SSH-agent exposure without printing key material.
