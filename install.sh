#!/usr/bin/env bash
# Install Vistal for the current user (no root needed; SteamOS-friendly).
#
#   ./install.sh            copy into ~/.local/lib/vistal, link ~/.local/bin/vistal
#   ./install.sh --dev      link to this checkout instead of copying
#   ./install.sh --esde     also register the "Games for Windows" system in ES-DE
#   ./install.sh --uninstall
set -euo pipefail

src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dest="${VISTAL_INSTALL_DIR:-$HOME/.local/lib/vistal}"
bindir="${VISTAL_BIN_DIR:-$HOME/.local/bin}"
mode=copy
esde=0

for arg in "$@"; do
    case "$arg" in
        --dev) mode="link" ;;
        --esde) esde=1 ;;
        --uninstall) mode=uninstall ;;
        -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

if [ "$mode" = uninstall ]; then
    rm -f "$bindir/vistal"
    rm -rf "$dest"
    echo "Removed $dest and $bindir/vistal."
    echo "Game prefixes and saves are kept in ${XDG_DATA_HOME:-$HOME/.local/share}/vistal."
    exit 0
fi

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    echo "Python 3.11 or newer is required (SteamOS 3.5+ ships it)." >&2
    exit 1
fi

mkdir -p "$bindir"
if [ "$mode" = link ]; then
    target="$src"
else
    rm -rf "$dest.new"
    mkdir -p "$dest.new"
    cp -r "$src/bin" "$src/vistal" "$dest.new/"
    [ -f "$src/README.md" ] && cp "$src/README.md" "$dest.new/"
    find "$dest.new" -name '__pycache__' -type d -prune -exec rm -rf {} +
    rm -rf "$dest"
    mv "$dest.new" "$dest"
    target="$dest"
fi
chmod +x "$target/bin/vistal"
ln -sfn "$target/bin/vistal" "$bindir/vistal"
echo "Installed: $bindir/vistal -> $target/bin/vistal"

case ":$PATH:" in
    *":$bindir:"*) ;;
    *) echo "Note: $bindir is not on your PATH; ES-DE finds Vistal there anyway." ;;
esac

if [ "$esde" = 1 ]; then
    "$bindir/vistal" frontend esde
fi

echo
"$bindir/vistal" doctor || true
