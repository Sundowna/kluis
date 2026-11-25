#!/usr/bin/env bash
# Kluis installer for Linux Mint (21/22) and other Ubuntu/Debian desktops. Installs for your user only.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$HOME/.local/share/kluis/app"
BIN="$HOME/.local/bin/kluis"
DESKTOP="$HOME/.local/share/applications/dev.kluis.Kluis.desktop"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
bold "Installing Kluis (unofficial Proton Drive client)…"

# 1. Dependencies: all preinstalled on Linux Mint; checked anyway.
missing=()
python3 -c 'import gi; gi.require_version("Gtk","3.0"); from gi.repository import Gtk' 2>/dev/null \
  || missing+=(python3-gi gir1.2-gtk-3.0)
python3 -c 'import gi; gi.require_version("XApp","1.0")' 2>/dev/null \
  || python3 -c 'import gi; gi.require_version("AyatanaAppIndicator3","0.1")' 2>/dev/null \
  || missing+=(gir1.2-xapp-1.0)
command -v gnome-keyring-daemon >/dev/null 2>&1 || missing+=(gnome-keyring)
if ((${#missing[@]})); then
  echo "Kluis needs: ${missing[*]}"
  read -r -p "Install them now with apt (asks for your password)? [Y/n] " ans
  if [[ "${ans:-Y}" =~ ^[Yy]$ ]]; then
    sudo apt-get install -y "${missing[@]}"
  else
    echo "Install them later with: sudo apt install ${missing[*]}"
  fi
fi

# 2. Program files
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR" "$(dirname "$BIN")" "$(dirname "$DESKTOP")" "$ICON_DIR"
cp -r "$HERE/kluis" "$APP_DIR/"
find "$APP_DIR" -name '__pycache__' -prune -exec rm -rf {} +

cat > "$BIN" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="$APP_DIR\${PYTHONPATH:+:\$PYTHONPATH}"
exec /usr/bin/python3 -m kluis "\$@"
EOF
chmod +x "$BIN"

# 3. Menu entry + icon
cp "$HERE/kluis/data/icons/dev.kluis.Kluis.svg" "$ICON_DIR/"
cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Kluis
GenericName=Proton Drive sync
Comment=Sync folders with Proton Drive (unofficial, uses the official Proton Drive CLI)
Exec=$BIN
Icon=dev.kluis.Kluis
Terminal=false
Categories=Network;FileTransfer;Utility;
Keywords=proton;drive;sync;cloud;backup;encrypted;
StartupNotify=true
SingleMainWindow=true
EOF
command -v update-desktop-database >/dev/null && update-desktop-database "$HOME/.local/share/applications" || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" || true

bold "Done."
echo "• Start it from the menu (search “Kluis”) or run: kluis"
echo "• First run walks you through getting the official Proton Drive CLI and signing in."
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "• Note: ~/.local/bin is not on your PATH yet; log out and in once.";; esac
read -r -p "Start Kluis now? [Y/n] " go
if [[ "${go:-Y}" =~ ^[Yy]$ ]]; then nohup "$BIN" >/dev/null 2>&1 & fi
