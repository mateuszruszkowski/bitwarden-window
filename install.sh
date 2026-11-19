#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ "$#" -gt 0 ]; then echo 'Usage: ./install.sh' >&2; exit 2; fi
if [ "$(id -u)" = 0 ]; then echo 'Install as your own user, without sudo.' >&2; exit 1; fi
case $(uname -s) in
  Darwin) platform=osx ;;
  Linux) platform=omarchy ;;
  *) echo 'Requires Omarchy Linux or macOS.' >&2; exit 1 ;;
esac
# Refuse to replace a shell helper managed by another tool.
lib="$HOME/.local/lib/bw-window"
if [ -L "$lib" ] || [ -L "$lib/.bitwarden-window-public" ]; then echo 'Unexpected symlink in installation.' >&2; exit 1; fi
if ! grep -qxF 'bitwarden-window/v1' "$lib/.bitwarden-window-public" 2>/dev/null; then
  for f in "$HOME/.local/bin/bw-unlock" "$lib"; do
    if [ -e "$f" ] || [ -L "$f" ]; then echo "Existing installation at $f; nothing overwritten." >&2; exit 1; fi
  done
fi
if [ "$platform" = omarchy ]; then
  mkdir -p "$HOME/.local/lib"
  exec 9<"$HOME/.local/lib"
  flock -nx 9 || { echo 'An unlock or installation is in progress.' >&2; exit 1; }
fi
"./$platform/install.sh"
python3 -I lib/install-shell.py
echo 'Open BW in the menu bar, or run ~/.local/bin/bw-unlock in a terminal.'
