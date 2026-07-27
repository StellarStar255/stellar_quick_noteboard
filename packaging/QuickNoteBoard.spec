# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec shared by all three platforms.
# Build from the repo root:  pyinstaller packaging/QuickNoteBoard.spec --noconfirm
import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
SRC = ROOT / "QuickNoteBoard.py"
VERSION = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"',
                    SRC.read_text(encoding="utf-8"), re.M).group(1)

# Human-facing name on macOS (.app), filesystem-safe name elsewhere.
DISPLAY_NAME = "Stellar Quick Noteboard"
DIST_NAME = "StellarQuickNoteboard"

if sys.platform == "darwin":
    icon_file = str(ROOT / "assets" / "icon.icns")
elif sys.platform == "win32":
    icon_file = str(ROOT / "assets" / "icon.ico")
else:
    icon_file = None

a = Analysis(
    [str(SRC)],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "assets" / "quick_note_board.png"), "assets")],
    hiddenimports=["PIL._tkinter_finder"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name=DIST_NAME,
    console=False,
    icon=icon_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name=DIST_NAME,
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{DISPLAY_NAME}.app",
        icon=icon_file,
        bundle_identifier="com.stellarstar.quicknoteboard",
        info_plist={
            "CFBundleName": DISPLAY_NAME,
            "CFBundleDisplayName": DISPLAY_NAME,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.productivity",
        },
    )
