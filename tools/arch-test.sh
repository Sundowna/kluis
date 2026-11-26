#!/bin/bash
# EndeavourOS/Arch check in a container (same steps as the CI "arch" job), KDE session variables.
# Usage (from the repo): podman run --rm -v "$PWD":/src:ro -v OUT:/out docker.io/library/archlinux:latest \
#                          bash /src/tools/arch-test.sh [FLOWS...]
set -euo pipefail
pacman -Syu --noconfirm --needed base-devel git python python-gobject python-cairo gtk3 librsvg gdk-pixbuf2 libsecret \
  libayatana-appindicator gnome-keyring xorg-server-xvfb xorg-xauth dbus imagemagick ttf-dejavu \
  adwaita-icon-theme tzdata at-spi2-core which >/out/pacman.log 2>&1
useradd -m tester
cp -r /src /home/tester/kluis && rm -rf /home/tester/kluis/dist && chown -R tester /home/tester/kluis
cd /home/tester/kluis
run() { su tester -c "cd /home/tester/kluis && $*"; }
echo "== tests"; for t in lint engine photos safety units; do run "python3 tests/test_$t.py" | tail -1; done
echo "== makepkg"
V="$(python3 -c 'import kluis; print(kluis.VERSION)')"
mkdir -p /tmp/build && cp packaging/arch/PKGBUILD /tmp/build/
sed -i "s|^source=.*|source=(\"kluis-$V.tar.gz\")|" /tmp/build/PKGBUILD
tar --transform "s,^,kluis-$V/," -czf "/tmp/build/kluis-$V.tar.gz" --exclude=.git --exclude=dist -C /home/tester/kluis .
useradd -m builder && chown -R builder /tmp/build
su builder -c "cd /tmp/build && makepkg --nodeps --noconfirm" >/out/makepkg.log 2>&1
cp /tmp/build/*.pkg.tar.zst /out/
echo "== pacman -U, start, remove"
pacman -U --noconfirm /tmp/build/*.pkg.tar.zst >/dev/null
pacman -Qi kluis | sed -n '1,3p'
pacman -Qi kluis | grep -E "^Depends On"
python3 -c "import gi; gi.require_version('AyatanaAppIndicator3','0.1'); print('panel icon library (StatusNotifier) ok')"
su tester -c 'XDG_CURRENT_DESKTOP=KDE xvfb-run -a -s "-screen 0 1440x900x24" dbus-run-session -- bash -c \
  "KLUIS_DEBUG=1 kluis >/tmp/kluis-run.log 2>&1 & sleep 12; import -window root /tmp/arch-kde.png; kill -0 \$! && echo Kluis is running; grep -m1 \"panel icon\" /tmp/kluis-run.log"'
cp /tmp/arch-kde.png /out/ 2>/dev/null || true
kluis --version
pacman -R --noconfirm kluis >/dev/null && test ! -e /usr/bin/kluis && echo "removed cleanly"
echo "== GUI flows (KDE)"
FLOWS="${*:-}"
run "JOBS=6 TZ=Europe/Zurich tests/gui/run_all.sh /tmp/flows-kde KDE $FLOWS" || true
cp -r /tmp/flows-kde /out/ ; tail -3 /tmp/flows-kde/results.txt
