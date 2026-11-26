#!/usr/bin/env bash
# Builds dist/Kluis-Setup-<version>.exe. Run in an MSYS2 UCRT64 shell with these packages:
#   pacman -S mingw-w64-ucrt-x86_64-{gtk3,python-gobject,python-cairo,librsvg,adwaita-icon-theme,pyinstaller}
# and Inno Setup 6 installed on Windows (ISCC.exe). CI does exactly this (.github/workflows/release.yml, job windows).
set -euo pipefail
cd "$(dirname "$0")/../.."
V="$(python -c 'import kluis; print(kluis.VERSION)')"
IFS=. read -r MA MI PA <<< "${V%%-*}"

python packaging/windows/make_icon.py packaging/windows/kluis.ico
cat > packaging/windows/version.txt <<EOF
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($MA, $MI, $PA, 0), prodvers=($MA, $MI, $PA, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'Kluis (unofficial, not affiliated with Proton AG)'),
    StringStruct('FileDescription', 'Kluis'),
    StringStruct('FileVersion', '$V'),
    StringStruct('InternalName', 'Kluis'),
    StringStruct('LegalCopyright', 'GPL-3.0-or-later'),
    StringStruct('OriginalFilename', 'Kluis.exe'),
    StringStruct('ProductName', 'Kluis'),
    StringStruct('ProductVersion', '$V')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
EOF

rm -rf build/Kluis dist/Kluis
pyinstaller --noconfirm --distpath dist --workpath build packaging/windows/kluis.spec
cp LICENSE dist/Kluis/LICENSE.txt

ISCC="${ISCC:-/c/Program Files (x86)/Inno Setup 6/ISCC.exe}"
"$ISCC" //Qp "//DVersion=$V" "//DSourceDir=$(cygpath -w "$PWD/dist/Kluis")" "//DOutputDir=$(cygpath -w "$PWD/dist")" \
  "$(cygpath -w packaging/windows/kluis.iss)"
ls -l dist/Kluis-Setup-"$V".exe
