# Shared .NET SDK installation for the environments that build C#.
# Source this file; do not execute it.
#
# dotnet-dev and godot-dev both need the SDK, and they must install the same
# one, so the step lives here and never in two copies.

# ensure_dotnet_sdk <root> <version> <sha512> - install the pinned upstream SDK.
#
# The distribution package stays installed. It is a different feature band, and
# the shell integration decides which command wins, so this function never
# removes it. The SDK layout is side-by-side: the function adds the pinned
# version and leaves every other version in place, so it never takes away an
# SDK that a global.json still selects.
ensure_dotnet_sdk() {
    local root=$1 version=$2 digest=$3
    local url tmp
    url=https://builds.dotnet.microsoft.com/dotnet/Sdk/$version/dotnet-sdk-$version-linux-x64.tar.gz

    if [ -x "$root/dotnet" ] && [ -d "$root/sdk/$version" ]; then
        ok "the .NET SDK $version is installed ($root)"
        return 0
    fi
    if [ "$DRY_RUN" = 1 ]; then
        info "would install the .NET SDK $version from $url"
        return 0
    fi

    tmp=$(mktemp -d) || die 'cannot create a temporary directory'
    curl -fsSL "$url" -o "$tmp/dotnet-sdk.tar.gz" || {
        rm -rf -- "$tmp"
        die "cannot download the .NET SDK $version from $url"
    }
    printf '%s  %s\n' "$digest" "$tmp/dotnet-sdk.tar.gz" | sha512sum -c - >/dev/null || {
        rm -rf -- "$tmp"
        die 'the .NET SDK download does not match DOTNET_SDK_SHA512 in manifests/dotnet-sdk.env'
    }
    mkdir -p -- "$root"
    tar -xzf "$tmp/dotnet-sdk.tar.gz" -C "$root" || {
        rm -rf -- "$tmp"
        die "cannot unpack the .NET SDK $version into $root"
    }
    rm -rf -- "$tmp"
    [ -d "$root/sdk/$version" ] || die "the archive does not contain sdk/$version"
    change "installed the .NET SDK $version"
}
