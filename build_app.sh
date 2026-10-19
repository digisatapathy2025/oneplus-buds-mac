#!/usr/bin/env bash
# ==============================================================================
# build_app.sh — Package OnePlus Buds macOS Companion into .app and .dmg
# ==============================================================================
set -euo pipefail

APP_NAME="OnePlus Buds"
BUNDLE_IDENTIFIER="com.digisatapathy.oneplusbuds"
VERSION="2.1.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="${SCRIPT_DIR}/dist"
APP_DIR="${DIST_DIR}/${APP_NAME}.app"
DMG_PATH="${DIST_DIR}/${APP_NAME}-${VERSION}.dmg"

echo "==> [1/5] Cleaning up existing dist output..."
rm -rf "${DIST_DIR}"
mkdir -p "${APP_DIR}/Contents/MacOS"
mkdir -p "${APP_DIR}/Contents/Resources"

echo "==> [2/5] Compiling native launcher binary..."
PY_CFLAGS=$(python3-config --cflags)
PY_LDFLAGS=$(python3-config --ldflags --embed)

# Build launcher from main.c
clang -O2 ${PY_CFLAGS} ${PY_LDFLAGS} -o "${APP_DIR}/Contents/MacOS/${APP_NAME}" "${SCRIPT_DIR}/main.c"
chmod +x "${APP_DIR}/Contents/MacOS/${APP_NAME}"

echo "==> [3/5] Bundling Python application resources..."
cp -R "${SCRIPT_DIR}/core" "${APP_DIR}/Contents/Resources/"
cp "${SCRIPT_DIR}/buds_app.py" "${APP_DIR}/Contents/Resources/"
cp "${SCRIPT_DIR}/buds.py" "${APP_DIR}/Contents/Resources/"
cp "${SCRIPT_DIR}/buds_controller.py" "${APP_DIR}/Contents/Resources/"
cp "${SCRIPT_DIR}/device_manager.py" "${APP_DIR}/Contents/Resources/"
cp "${SCRIPT_DIR}/bluetooth_monitor.py" "${APP_DIR}/Contents/Resources/"
cp "${SCRIPT_DIR}/live_device_compatibility_catalog.json" "${APP_DIR}/Contents/Resources/"
cp "${SCRIPT_DIR}/device_catalog_decrypted.json" "${APP_DIR}/Contents/Resources/"

echo "==> [4/5] Generating Info.plist..."
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
    <string>14.0</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSBluetoothAlwaysUsageDescription</key>
    <string>OnePlus Buds requires Bluetooth access to connect, monitor battery, and control active noise cancellation.</string>
</dict>
</plist>
EOF

# Ad-hoc sign the bundle
echo "==> Code signing application (ad-hoc)..."
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
echo " Packaging complete!"
echo " App Bundle:  ${APP_DIR}"
echo " Disk Image:  ${DMG_PATH}"
echo "======================================================================"
