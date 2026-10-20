#!/usr/bin/env bash
# ==============================================================================
# build_app.sh — Package 100% Native Swift OnePlus Buds into .app and .dmg
# ==============================================================================
set -euo pipefail

APP_NAME="OnePlus Buds"
BUNDLE_IDENTIFIER="com.digisatapathy.oneplusbuds"
VERSION="2.1.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="${SCRIPT_DIR}/dist"
APP_DIR="${DIST_DIR}/${APP_NAME}.app"
DMG_PATH="${DIST_DIR}/${APP_NAME}-${VERSION}.dmg"
SWIFT_DIR="${SCRIPT_DIR}/swift"

echo "==> [1/5] Cleaning previous build artifacts..."
rm -rf "${DIST_DIR}"
mkdir -p "${APP_DIR}/Contents/MacOS"
mkdir -p "${APP_DIR}/Contents/Resources"

echo "==> [2/5] Compiling 100% Native Swift release binaries..."
(
    cd "${SWIFT_DIR}"
    swift build -c release
)

echo "==> [3/5] Installing native Mach-O executable..."
cp "${SWIFT_DIR}/.build/release/OnePlusBudsApp" "${APP_DIR}/Contents/MacOS/${APP_NAME}"
chmod +x "${APP_DIR}/Contents/MacOS/${APP_NAME}"

# Also copy CLI binary if built
if [ -f "${SWIFT_DIR}/.build/release/buds" ]; then
    mkdir -p "${DIST_DIR}/bin"
    cp "${SWIFT_DIR}/.build/release/buds" "${DIST_DIR}/bin/buds"
fi

echo "==> [4/5] Generating Info.plist & code signing..."
cat <<EOF > "${APP_DIR}/Contents/Info.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>en</string>
    <key>CFBundleExecutable</key>
    <string>${APP_NAME}</string>
    <key>CFBundleIdentifier</key>
    <string>${BUNDLE_IDENTIFIER}</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>${VERSION}</string>
    <key>CFBundleVersion</key>
    <string>${VERSION}</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSBluetoothAlwaysUsageDescription</key>
    <string>OnePlus Buds requires Bluetooth access to connect, monitor battery, and control active noise cancellation.</string>
</dict>
</plist>
EOF

echo "==> Ad-hoc code signing native app bundle..."
codesign --force --deep --sign - "${APP_DIR}"

echo "==> [5/5] Building distributable .dmg..."
DMG_TEMP_DIR="${DIST_DIR}/dmg_staging"
mkdir -p "${DMG_TEMP_DIR}"
cp -R "${APP_DIR}" "${DMG_TEMP_DIR}/"
ln -s /Applications "${DMG_TEMP_DIR}/Applications"

hdiutil create -volname "${APP_NAME}" -srcfolder "${DMG_TEMP_DIR}" -ov -format UDZO "${DMG_PATH}"
rm -rf "${DMG_TEMP_DIR}"

echo ""
echo "======================================================================"
echo " Packaging complete (100% Native Swift)!"
echo " App Bundle:  ${APP_DIR}"
echo " Disk Image:  ${DMG_PATH}"
echo " App Size:    $(du -sh "${APP_DIR}" | cut -f1)"
echo " DMG Size:    $(du -sh "${DMG_PATH}" | cut -f1)"
echo "======================================================================"
