#!/usr/bin/env bash
# Builds dist/kluis_<version>_all.deb from this source tree. Usage: packaging/build-deb.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(python3 -c "import sys; sys.path.insert(0,'$ROOT'); import kluis; print(kluis.VERSION)")"
B="$(mktemp -d)/kluis"
mkdir -p "$B/DEBIAN" "$B/usr/lib/kluis" "$B/usr/bin" "$B/usr/share/applications" \
         "$B/usr/share/icons/hicolor/scalable/apps" "$B/usr/share/doc/kluis" "$ROOT/dist"
cp -r "$ROOT/kluis" "$B/usr/lib/kluis/"
find "$B" -name __pycache__ -prune -exec rm -rf {} +
printf '#!/bin/sh\nexport PYTHONPATH="/usr/lib/kluis${PYTHONPATH:+:$PYTHONPATH}"\nexec /usr/bin/python3 -m kluis "$@"\n' > "$B/usr/bin/kluis"
cp "$ROOT/kluis/data/icons/dev.kluis.Kluis.svg" "$B/usr/share/icons/hicolor/scalable/apps/"
cp "$ROOT/README.md" "$ROOT/LICENSE" "$B/usr/share/doc/kluis/"
cat > "$B/usr/share/applications/dev.kluis.Kluis.desktop" <<'DESK'
[Desktop Entry]
Type=Application
Name=Kluis
GenericName=Proton Drive sync
Comment=Sync folders and photos with Proton Drive (unofficial, uses the official Proton Drive CLI)
Exec=kluis
Icon=dev.kluis.Kluis
Terminal=false
Categories=Network;FileTransfer;Utility;Graphics;Photography;
Keywords=proton;drive;photos;sync;cloud;backup;encrypted;
StartupNotify=true
SingleMainWindow=true
DESK
cat > "$B/DEBIAN/control" <<CTRL
Package: kluis
Version: $VERSION
Section: net
Priority: optional
Architecture: all
Installed-Size: $(du -sk "$B/usr" | cut -f1)
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-3.0, gir1.2-gdkpixbuf-2.0, gir1.2-xapp-1.0 | gir1.2-ayatanaappindicator3-0.1
Recommends: gnome-keyring, ffmpegthumbnailer, gir1.2-cinnamondesktop-3.0 | gir1.2-gnomedesktop-3.0
Maintainer: Sundowna <noreply@github.com>
Homepage: https://github.com/Sundowna/kluis
Description: Unofficial Proton Drive desktop client (Kluis)
 Syncs a list of folders with Proton Drive (two-way, backup or mirror) and
 keeps a local copy of Proton Photos, with a panel icon, Drive browser, photo
 gallery and activity log. All transfers go through Proton's official Proton
 Drive CLI, which Kluis downloads on first run. Not affiliated with Proton AG.
CTRL
printf '#!/bin/sh\nset -e\ncommand -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -f /usr/share/icons/hicolor || true\ncommand -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true\nexit 0\n' > "$B/DEBIAN/postinst"
printf '#!/bin/sh\npkill -f "^/usr/bin/python3 -m kluis" 2>/dev/null || true\nexit 0\n' > "$B/DEBIAN/prerm"
find "$B/usr" -type d -exec chmod 755 {} +
find "$B/usr/lib" "$B/usr/share" -type f -exec chmod 644 {} +
chmod 755 "$B/DEBIAN/postinst" "$B/DEBIAN/prerm" "$B/usr/bin/kluis"
dpkg-deb --root-owner-group --build "$B" "$ROOT/dist/kluis_${VERSION}_all.deb"
