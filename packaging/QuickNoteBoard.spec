# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec shared by all three platforms — builds the PySide6 (v2) app.
# Build from the repo root:  pyinstaller packaging/QuickNoteBoard.spec --noconfirm
import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
SRC = ROOT / "noteboard" / "__main__.py"
VERSION = re.search(r'^APP_VERSION = "([^"]+)"',
                    (ROOT / "noteboard" / "core" / "version.py").read_text(encoding="utf-8"),
                    re.M).group(1)

# Human-facing name on macOS (.app), filesystem-safe name elsewhere.
# DIST_NAME must never change: the in-app updater of already-installed
# versions matches release assets by this prefix.
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
    excludes=[
        "tkinter", "_tkinter",
        # Heavy Qt submodules the app never imports.
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebChannel", "PySide6.QtWebSockets",
        "PySide6.QtPdf", "PySide6.QtPdfWidgets",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets", "PySide6.QtPositioning",
        "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSql",
        "PySide6.QtTest", "PySide6.QtBluetooth", "PySide6.QtNfc",
        "PySide6.QtRemoteObjects", "PySide6.QtScxml",
        "PySide6.QtTextToSpeech", "PySide6.QtVirtualKeyboard",
        "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools",
    ],
    noarchive=False,
)

# Prune Qt plugin families the app cannot use. Input-method and platform
# plugins stay — Chinese IME support depends on them.
_DROP_PLUGIN_DIRS = (
    "qml", "quick", "webengine", "multimedia", "3d", "charts", "pdf",
    "position", "sensors", "sqldrivers", "designer", "qmltooling",
    "scenegraph", "assetimporters", "virtualkeyboard", "texttospeech",
    "canbus", "webview", "renderers", "renderplugins", "sceneparsers",
    "geometryloaders", "geoservices",
)

def _keep(entry):
    dest = entry[0].replace("\\", "/").lower()
    marker = "qt/plugins/" if "qt/plugins/" in dest else (
        "plugins/" if ("pyside6" in dest and "/plugins/" in dest) else None)
    if marker is None:
        return True
    sub = dest.split("plugins/", 1)[1]
    return not sub.startswith(_DROP_PLUGIN_DIRS)

a.binaries = [b for b in a.binaries if _keep(b)]
a.datas = [d for d in a.datas if _keep(d)]

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
