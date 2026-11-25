#!/usr/bin/env bash
# Removes Kluis. Your files, Proton Drive and the proton-drive CLI are left alone.
# --purge also removes Kluis settings, sync state and logs.
set -euo pipefail
pkill -f "^/usr/bin/python3 -m kluis" 2>/dev/null || true
rm -rf "$HOME/.local/share/kluis/app"
rm -f "$HOME/.local/bin/kluis" \
      "$HOME/.local/share/applications/dev.kluis.Kluis.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/dev.kluis.Kluis.svg" \
      "$HOME/.config/autostart/kluis.desktop"
if [[ "${1:-}" == "--purge" ]]; then
  rm -rf "$HOME/.config/kluis" "$HOME/.local/share/kluis" "$HOME/.local/state/kluis"
  echo "Kluis removed, including settings and sync state."
else
  echo "Kluis removed. Settings kept in ~/.config/kluis (use --purge to remove them too)."
fi
echo "To also remove the Proton Drive CLI: rm ~/.local/bin/proton-drive  (sign out first in Kluis or run: proton-drive auth logout)"
