# The isolated Rust toolchain, and the tools installed by cargo, rustup,
# Claude Code, and Codex. CARGO_HOME and RUSTUP_HOME stay inside this
# container HOME, so no Rust state reaches the host or another environment.
export RUSTUP_HOME="$HOME/.rustup"
export CARGO_HOME="$HOME/.cargo"
for dir in "$CARGO_HOME/bin" "$HOME/.local/bin"; do
    case ":${PATH:-}:" in
        *":$dir:"*) ;;
        *) export PATH="$dir${PATH:+:$PATH}" ;;
    esac
done
unset dir
