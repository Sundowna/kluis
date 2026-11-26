# PyInstaller spec for Kluis on Windows. Build in an MSYS2 UCRT64 shell (see packaging/windows/build.sh):
#   pyinstaller --noconfirm packaging/windows/kluis.spec
# Result: dist/Kluis/Kluis.exe with GTK 3, Adwaita icons, the SVG loader and Kluis's own data next to it.
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

a = Analysis(
    [os.path.join(SPECPATH, "kluis_main.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "kluis", "data"), os.path.join("kluis", "data"))],
    hiddenimports=["kluis.app", "kluis.wintray", "kluis.winsingle", "kluis.selftest", "gi._gi_cairo", "cairo",
                   "winreg"],
    hooksconfig={
        "gi": {
            "icons": ["Adwaita", "hicolor"],
            "themes": ["Adwaita"],
            "languages": ["en_GB", "en_US", "de", "nl", "af"],
            "module-versions": {"Gtk": "3.0", "Gdk": "3.0", "GdkPixbuf": "2.0"},
        },
    },
    excludes=["tkinter", "unittest", "pydoc", "test"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [("X utf8_mode=1", None, "OPTION")],         # text files are UTF-8, like on Linux
    exclude_binaries=True,
    name="Kluis",
    icon=os.path.join(SPECPATH, "kluis.ico"),
    console=False,
    version=os.path.join(SPECPATH, "version.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="Kluis")
