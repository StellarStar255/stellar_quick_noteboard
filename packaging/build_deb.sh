#!/usr/bin/env bash
# Build the Debian/Ubuntu package.
# Usage: packaging/build_deb.sh <version>
# Run from the repo root after: pyinstaller packaging/QuickNoteBoard.spec --noconfirm
set -euo pipefail

VERSION="${1:?usage: build_deb.sh <version>}"
PKG="stellar-quick-noteboard"
ARCH="$(dpkg --print-architecture)"
STAGE="build/deb"
APP_DIR="dist/StellarQuickNoteboard"

[ -d "$APP_DIR" ] || { echo "error: $APP_DIR not found (run pyinstaller first)"; exit 1; }

rm -rf "$STAGE"
mkdir -p \
    "$STAGE/DEBIAN" \
    "$STAGE/opt/$PKG" \
    "$STAGE/usr/bin" \
    "$STAGE/usr/share/applications" \
    "$STAGE/usr/share/icons/hicolor/512x512/apps"

cp -r "$APP_DIR"/. "$STAGE/opt/$PKG/"
ln -s "/opt/$PKG/StellarQuickNoteboard" "$STAGE/usr/bin/$PKG"

python3 - <<EOF
from PIL import Image
Image.open("assets/quick_note_board.png").resize((512, 512)) \
    .save("$STAGE/usr/share/icons/hicolor/512x512/apps/$PKG.png")
EOF

cat > "$STAGE/usr/share/applications/$PKG.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Stellar Quick Noteboard
Name[zh_CN]=Stellar 快速记事板
Comment=Lightweight desktop note-taking app
Comment[zh_CN]=轻量级桌面笔记应用
Exec=/opt/$PKG/StellarQuickNoteboard
Icon=$PKG
Terminal=false
Categories=Office;Utility;
EOF

INSTALLED_SIZE="$(du -sk "$STAGE" --exclude=DEBIAN | cut -f1)"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Section: editors
Priority: optional
Architecture: $ARCH
Installed-Size: $INSTALLED_SIZE
Maintainer: StellarStar255 <goosehuangmatt@gmail.com>
Depends: libxcb-cursor0
Recommends: fonts-noto-cjk, ibus
Homepage: https://github.com/StellarStar255/stellar_quick_noteboard
Description: Lightweight desktop note-taking app
 Multiple notebooks, markdown rendering, clipboard image paste,
 automatic backups and bilingual (Chinese/English) UI.
EOF

DEB="dist/${PKG}_${VERSION}_${ARCH}.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$DEB"
echo "==> Done: $DEB"
