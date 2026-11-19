#!/bin/sh
set -eu
cd "$(dirname "$0")"
[ "$#" = 0 ] || { echo 'Usage: ./uninstall.sh' >&2; exit 2; }
lib="$HOME/.local/lib/bw-window"
[ ! -L "$lib" ] && [ ! -L "$lib/.bitwarden-window-public" ] && grep -qxF 'bitwarden-window/v1' "$lib/.bitwarden-window-public" 2>/dev/null || { echo 'No owned installation found.' >&2; exit 1; }
case $(uname -s) in
 Darwin) ./osx/uninstall.sh ;;
 Linux)
   exec 9<"$HOME/.local/lib"
   flock -nx 9 || { echo 'An unlock or installation is in progress.' >&2; exit 1; }
   ./omarchy/uninstall.sh ;;
 *) exit 2 ;;
esac
rm -f "$HOME/.local/bin/bw-unlock" "$lib/auth.py" "$lib/shell.sh" "$lib/native-bw"
# Remove only bytecode for modules this installer owns.
for cache in "$lib"/__pycache__/core.cpython-*.pyc "$lib"/__pycache__/auth.cpython-*.pyc; do
  [ ! -f "$cache" ] || rm -f "$cache"
done
rmdir "$lib/__pycache__" 2>/dev/null || :
if [ -d "$lib" ] && ! rmdir "$lib" 2>/dev/null; then
  echo "Preserved extra files at $lib. Move them before reinstalling."
fi
echo 'Remove any source line for shell.sh that you added to your shell profile.'
