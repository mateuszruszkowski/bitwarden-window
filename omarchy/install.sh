#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
umask 077
[[ $(uname -s) == Linux && $(id -u) != 0 ]] || { echo "Run as your Omarchy desktop user." >&2; exit 2; }
for prog in bw systemctl systemd-run omarchy ghostty hyprctl; do
  command -v "$prog" >/dev/null || { echo "Missing prerequisite: $prog" >&2; exit 1; }
done
/usr/bin/python3 -I -c 'import os, time, sys; sys.exit(not (hasattr(os, "timerfd_create") and hasattr(time, "CLOCK_BOOTTIME")))' || { echo "Requires system Python 3.13+ with timerfd support." >&2; exit 1; }
omarchy shell shell ping | grep -qx ok || { echo 'Run in a logged-in Omarchy desktop session.' >&2; exit 1; }
systemctl --user show-environment >/dev/null
omarchy plugin validate "$PWD/plugin"
lib="$HOME/.local/lib/bw-window"
client="$HOME/.local/bin/bw-window"
unit="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/bw-window-relock.service"
plugin="$HOME/.config/omarchy/plugins/community.bitwarden-window"
marker=.bitwarden-window-public
if [[ -L $lib || -L $plugin || -L $lib/$marker || -L $plugin/$marker ]]; then
  echo 'Unexpected symlink at an installation directory or marker.' >&2; exit 1
fi
if ! grep -Fxq bitwarden-window/v1 "$lib/$marker" 2>/dev/null; then
  for target in "$lib" "$client" "$plugin" "$unit"; do
    [[ ! -e $target && ! -L $target ]] || { echo "Existing path $target; nothing overwritten." >&2; exit 1; }
  done
elif [[ -e $plugin ]] && ! grep -Fxq bitwarden-window/v1 "$plugin/$marker" 2>/dev/null; then
  echo 'Conflicting plugin directory.' >&2; exit 1
fi
if systemctl --user is-active --quiet bw-window.service; then
  echo 'Run ~/.local/bin/bw-window lock before updating.' >&2; exit 1
fi
fresh_plugin=true
[[ ! -e "$plugin/$marker" ]] || fresh_plugin=false
if [[ -L $unit ]] || { [[ -e $unit ]] && ! cmp -s bw-window-relock.service "$unit"; }; then echo "Existing user unit at $unit." >&2; exit 1; fi
mkdir -p "$lib" "$HOME/.local/bin" "${plugin%/*}" "${unit%/*}"
printf '%s\n' bitwarden-window/v1 > "$lib/$marker"
install -m 600 ../lib/core.py "$lib/core.py"
install -m 700 bw-window "$client"
/usr/bin/python3 -I ../lib/install-paths.py "$lib/paths.json" "$(type -P bw)" "$(type -P age-keygen || :)"
install -m 600 bw-window-relock.service "$unit"
systemctl --user daemon-reload
systemctl --user enable bw-window-relock.service
mkdir -p "$plugin/bin" "$plugin/i18n"
printf '%s\n' bitwarden-window/v1 > "$plugin/$marker"
install -m600 plugin/manifest.json plugin/BarWidget.qml "$plugin/"
install -m600 plugin/i18n/*.json "$plugin/i18n/"
install -m700 plugin/bin/unlock "$plugin/bin/"
omarchy shell shell rescanPlugins
if $fresh_plugin; then
  omarchy plugin enable community.bitwarden-window --section centerEnd --index 0
else
  echo "If the widget still shows the previous version, run omarchy restart shell."
fi
