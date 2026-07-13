#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
CONFIGURATION="${CONFIGURATION:-release}"
swift build -c "$CONFIGURATION"
BIN_PATH="$(swift build -c "$CONFIGURATION" --show-bin-path)"
APP_PATH=".build/On Air.app"

rm -rf "$APP_PATH"
mkdir -p "$APP_PATH/Contents/MacOS" "$APP_PATH/Contents/Resources"
cp "$BIN_PATH/OnAir" "$APP_PATH/Contents/MacOS/OnAir"
cp Resources/Info.plist "$APP_PATH/Contents/Info.plist"
codesign --force --deep --sign - "$APP_PATH"
echo "$APP_PATH"
