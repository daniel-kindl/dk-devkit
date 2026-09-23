# Keep .NET CLI state inside the isolated godot-dev home.
export DOTNET_CLI_HOME="$HOME/.dotnet"

# Put the pinned upstream SDK in front of the distribution package. Fedora
# packages feature band 1xx only, and no global.json rollForward policy moves
# down a band, so /usr/bin/dotnet cannot build a repository that pins another
# band. manifests/dotnet-sdk.env says why.
#
# The guard keeps the box usable before the bootstrap has run: without the
# directory the distribution command stays in charge, and DOTNET_ROOT does not
# point at a path that does not exist.
if [ -d "$HOME/.local/share/dotnet" ]; then
    export DOTNET_ROOT="$HOME/.local/share/dotnet"
    case ":$PATH:" in
        *":$DOTNET_ROOT:"*) ;;
        *) PATH="$DOTNET_ROOT:$PATH"; export PATH ;;
    esac
fi
