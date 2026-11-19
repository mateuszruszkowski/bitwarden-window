#!/bin/bash
set -euo pipefail
lib="$HOME/.local/lib/bw-window"
plugin="$HOME/.config/omarchy/plugins/community.bitwarden-window"
unit="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/bw-window-relock.service"
marker=.bitwarden-window-public
[[ ! -L $lib && ! -L $lib/$marker ]] && grep -qxF bitwarden-window/v1 "$lib/$marker" 2>/dev/null || { echo 'Installation marker missing.' >&2; exit 1; }
if [[ -e $plugin || -L $plugin ]]; then
  [[ ! -L $plugin && ! -L $plugin/$marker ]] && grep -qxF bitwarden-window/v1 "$plugin/$marker" 2>/dev/null || { echo 'Unrecognized plugin directory.' >&2; exit 1; }
fi
systemctl --user show-environment >/dev/null
if systemctl --user is-active --quiet bw-window.service || [[ -e $HOME/.local/state/bw-window/relock-required ]]; then
  "$HOME/.local/bin/bw-window" lock
fi
if [[ -e $unit ]]; then
  cmp -s "$(dirname "$0")/bw-window-relock.service" "$unit" || { echo "Unrecognized unit at $unit." >&2; exit 1; }
  systemctl --user disable bw-window-relock.service
  rm -f "$unit"
  systemctl --user daemon-reload
fi
if [[ -d $plugin ]]; then
  omarchy plugin disable community.bitwarden-window || echo 'The desktop was unavailable. Remove the BW entry from your layout if it remains.'
  rm -f "$plugin/BarWidget.qml" "$plugin/manifest.json" "$plugin/i18n/en.json" "$plugin/i18n/pl.json" "$plugin/bin/unlock" "$plugin/$marker"
  rmdir "$plugin/i18n" "$plugin/bin" "$plugin" 2>/dev/null || :
fi
rm -f "$HOME/.local/bin/bw-window" "$lib/core.py" "$lib/paths.json" "$lib/$marker"
omarchy shell shell rescanPlugins >/dev/null 2>&1 || :
