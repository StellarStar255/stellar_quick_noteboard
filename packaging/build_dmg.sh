#!/usr/bin/env bash
# Build (and optionally sign + notarize) the macOS dmg.
# Usage: packaging/build_dmg.sh <version>
# Run from the repo root after: pyinstaller packaging/QuickNoteBoard.spec --noconfirm
#
# Signing is controlled by environment variables; every step degrades
# gracefully so unsigned local/CI builds still work:
#   MACOS_SIGN_IDENTITY   "Developer ID Application: Name (TEAMID)" -> real signing
#   APPLE_ID + APPLE_TEAM_ID + APPLE_APP_PASSWORD -> notarization + stapling
set -euo pipefail

VERSION="${1:?usage: build_dmg.sh <version>}"
APP="dist/Stellar Quick Noteboard.app"
DMG="dist/StellarQuickNoteboard-${VERSION}-macOS.dmg"
IDENTITY="${MACOS_SIGN_IDENTITY:-}"

[ -d "$APP" ] || { echo "error: $APP not found (run pyinstaller first)"; exit 1; }

if [ -n "$IDENTITY" ]; then
    echo "==> Codesigning with: $IDENTITY"
    codesign --force --deep --options runtime --timestamp \
        --entitlements packaging/entitlements.plist \
        --sign "$IDENTITY" "$APP"
else
    echo "==> MACOS_SIGN_IDENTITY not set; ad-hoc signing (Gatekeeper will warn)"
    codesign --force --deep --sign - "$APP"
fi
codesign --verify --verbose=1 "$APP"

echo "==> Building $DMG"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
rm -f "$DMG"
hdiutil create -volname "Stellar Quick Noteboard" -srcfolder "$STAGE" \
    -ov -format UDZO "$DMG"

if [ -n "$IDENTITY" ]; then
    codesign --force --timestamp --sign "$IDENTITY" "$DMG"
fi

if [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ] && [ -n "${APPLE_APP_PASSWORD:-}" ]; then
    echo "==> Notarizing"
    xcrun notarytool submit "$DMG" \
        --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" \
        --password "$APPLE_APP_PASSWORD" --wait
    xcrun stapler staple "$DMG"
else
    echo "==> Notarization credentials not set; skipping"
fi

echo "==> Done: $DMG"
