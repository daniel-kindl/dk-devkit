# Keep Go's workspace and installed tools inside the isolated golang-dev home.
export GOPATH="$HOME/go"
case ":${PATH:-}:" in
    *":$GOPATH/bin:"*) ;;
    *) export PATH="$GOPATH/bin${PATH:+:$PATH}" ;;
esac
