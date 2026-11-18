#!/bin/bash
# Build script for macOS 10.15 Catalina (Intel x86_64)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

APP_NAME="WinRA"
export MACOSX_DEPLOYMENT_TARGET="10.15"

echo "=== WinRA Build Script for macOS Catalina 10.15 ==="
echo "Target: macOS 10.15 Catalina (x86_64)"
echo "MACOSX_DEPLOYMENT_TARGET=$MACOSX_DEPLOYMENT_TARGET"

# Python executable detection
if [ -n "$PYTHON_BIN" ]; then
    PYTHON="$PYTHON_BIN"
elif [ -f "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3" ]; then
    PYTHON="/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
elif command -v python3.11 &>/dev/null; then
    PYTHON="python3.11"
elif [ -f "/usr/local/bin/python3" ]; then
    PYTHON="/usr/local/bin/python3"
else
    PYTHON="python3"
fi

echo "Using Python: $PYTHON ($($PYTHON --version))"

VENV_DIR="$SCRIPT_DIR/venv_catalina"
rm -rf "$VENV_DIR"

echo "Creating x86_64 virtual environment..."
arch -x86_64 "$PYTHON" -m venv "$VENV_DIR" || "$PYTHON" -m venv "$VENV_DIR"

VENV_PY="$VENV_DIR/bin/python3"
VENV_PIP="$VENV_DIR/bin/pip"
VENV_PYINSTALLER="$VENV_DIR/bin/pyinstaller"

echo "Installing dependencies..."
arch -x86_64 "$VENV_PIP" install --upgrade pip setuptools wheel || "$VENV_PIP" install --upgrade pip setuptools wheel
arch -x86_64 "$VENV_PIP" install -r requirements.txt || "$VENV_PIP" install -r requirements.txt
arch -x86_64 "$VENV_PIP" install "pyinstaller>=6.0" || "$VENV_PIP" install "pyinstaller>=6.0"

echo "Cleaning previous builds..."
rm -rf build dist "${APP_NAME}-Catalina-10.15.dmg" "${APP_NAME}-Catalina-10.15.pkg"

# Ensure bin directory has executable permission
if [ -d "$SCRIPT_DIR/bin" ]; then
    chmod +x "$SCRIPT_DIR/bin/"* 2>/dev/null || true
fi

echo "Building ${APP_NAME}.app with PyInstaller for x86_64..."
arch -x86_64 "$VENV_PYINSTALLER" \
    --name "$APP_NAME" \
    --windowed \
    --onedir \
    --target-arch x86_64 \
    --noconfirm \
    --clean \
    --add-data "app:app" \
    --add-data "bin:bin" \
    --hidden-import customtkinter \
    --hidden-import PIL \
    --hidden-import rarfile \
    --hidden-import darkdetect \
    --collect-all customtkinter \
    main.py

echo "Verifying compiled binary architecture and deployment target..."
file "dist/${APP_NAME}.app/Contents/MacOS/${APP_NAME}"
otool -l "dist/${APP_NAME}.app/Contents/MacOS/${APP_NAME}" | grep -A 4 -E "LC_BUILD_VERSION|LC_VERSION_MIN_MACOSX" || true

# Fix permissions
chmod -R u+w "dist/${APP_NAME}.app"
chmod +x "dist/${APP_NAME}.app/Contents/MacOS/${APP_NAME}"
if [ -d "dist/${APP_NAME}.app/Contents/Resources/bin" ]; then
    chmod +x dist/${APP_NAME}.app/Contents/Resources/bin/*
fi

echo "Stripping quarantine and signing ad-hoc..."
xattr -cr "dist/${APP_NAME}.app"
codesign -s - --force --all-architectures --deep "dist/${APP_NAME}.app" 2>/dev/null || true

echo "Creating Catalina-compatible DMG with HFS+ filesystem..."
DMG_DIR="$SCRIPT_DIR/dmg_catalina_temp"
rm -rf "$DMG_DIR"
mkdir -p "$DMG_DIR"

cp -R "dist/${APP_NAME}.app" "$DMG_DIR/"
ln -s /Applications "$DMG_DIR/Applications"

# Notice: -fs HFS+ ensures Catalina mounts without APFS compatibility bugs
hdiutil create \
    -volname "$APP_NAME" \
    -srcfolder "$DMG_DIR" \
    -ov \
    -format UDZO \
    -fs HFS+ \
    "${APP_NAME}-Catalina-10.15.dmg"

rm -rf "$DMG_DIR"

echo "Creating PKG installer..."
APP_NAME="$APP_NAME" APP_PATH="dist/${APP_NAME}.app" PKG_NAME="${APP_NAME}-Catalina-10.15.pkg" \
bash "$SCRIPT_DIR/build_pkg.sh" 2>/dev/null || true

echo "=== Build Finished Successfully ==="
ls -lh "${APP_NAME}-Catalina-10.15.dmg" "${APP_NAME}-Catalina-10.15.pkg" || ls -lh "${APP_NAME}-Catalina-10.15.dmg"
