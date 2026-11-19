#!/bin/bash
# Build Hearth-<version>.dmg (drag-to-Applications disk image) on an Apple-silicon Mac.
# Needs Xcode or the Command Line Tools. Optional second output: MAKE_PKG=1 also builds a .pkg.
#
#   ./build.sh                                      unsigned (fine for your own Macs)
#   APP_SIGN_ID="Developer ID Application: NAME (TEAMID)" \
#   NOTARY_PROFILE=my-notary-profile ./build.sh     signed + notarized + stapled (app and disk image)
#   (.pkg additionally needs INSTALLER_SIGN_ID="Developer ID Installer: NAME (TEAMID)")
#
# Optional: PYTHON_TARBALL=/path/to/the pinned cpython tarball below  (skip the download; still checksum-verified)
#
# Everything bundled is pinned: the Python runtime by URL + sha256 (below), every Python package by
# version + sha256 (installer/requirements-app.lock, regenerated with installer/lock.sh). Models are
# NOT bundled; Hearth.app downloads them on first launch, with consent, from models/manifest.json.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20260718/cpython-3.12.13%2B20260718-aarch64-apple-darwin-install_only.tar.gz"
PBS_SHA256="62aeee6161d57303a71a138b75fd5cc6fb8c89c4b1d9c7f0a052d89fa0b6652b"
[ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = arm64 ] || { echo "Run this on an Apple-silicon Mac."; exit 1; }

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$(cd "$HERE/.." && pwd)"
VERSION="$(/usr/bin/python3 -c "import re,sys;print(re.search(r'VERSION = \"([^\"]+)\"',open('$SRC/app/main.py').read()).group(1))")"
BUILD="$HERE/build"
STAGE="$BUILD/root"
APP="$STAGE/Hearth.app"
RES="$APP/Contents/Resources"
CACHE="$BUILD/cache"
rm -rf "$STAGE" "$BUILD/Hearth-$VERSION.pkg" "$BUILD/Hearth-$VERSION.dmg" "$BUILD/component.plist" "$BUILD/dmg"
mkdir -p "$APP/Contents/MacOS" "$RES" "$CACHE"

echo "==> App bundle ($VERSION)"
sed "s|@VERSION@|$VERSION|g" "$HERE/Info.plist" >"$APP/Contents/Info.plist"
cp "$HERE/Hearth-launcher.sh" "$APP/Contents/MacOS/Hearth" && chmod 755 "$APP/Contents/MacOS/Hearth"
cp "$HERE/assets/AppIcon.icns" "$RES/AppIcon.icns"
printf '%s+%s' "$VERSION" "$(date +%Y%m%d%H%M%S)" >"$RES/VERSION"   # lets the launcher restart the service after an upgrade
cp -R "$SRC/app" "$SRC/config" "$SRC/dist" "$SRC/tools" "$SRC/models" "$RES/"
cp "$SRC/run_server.py" "$SRC/requirements.txt" "$RES/"
mkdir -p "$RES/launchd" && cp "$HERE/launchd/com.hearth.local.plist.template" "$HERE/launchd/com.hearth.llm.plist.template" "$RES/launchd/"
# Refuse to ship a manifest that would download anything unpinned.
/usr/bin/python3 "$SRC/scripts/pin_models.py" --check
cp "$HERE/uninstall.sh" "$RES/uninstall.sh" && chmod 755 "$RES/uninstall.sh"

echo "==> Bundled Python runtime (pinned)"
TARBALL="${PYTHON_TARBALL:-$CACHE/$(basename "$PBS_URL" | sed 's/%2B/+/')}"
[ -f "$TARBALL" ] || /usr/bin/curl -fsSL "$PBS_URL" -o "$TARBALL"
GOT="$(/usr/bin/shasum -a 256 "$TARBALL" | awk '{print $1}')"
[ "$GOT" = "$PBS_SHA256" ] || { echo "Python runtime checksum mismatch: $GOT"; rm -f "$TARBALL"; exit 1; }
mkdir -p "$BUILD/py-extract" && rm -rf "$BUILD/py-extract"/* && tar -xzf "$TARBALL" -C "$BUILD/py-extract"
mv "$BUILD/py-extract/python" "$RES/python"

echo "==> Python packages from installer/requirements-app.lock (hash-checked, wheels only)"
"$RES/python/bin/python3" -m pip install --no-cache-dir --disable-pip-version-check \
  --require-hashes --only-binary :all: --no-deps -r "$HERE/requirements-app.lock"
"$RES/python/bin/python3" -m pip check

selfcheck() {  # label
  echo "==> Self-check inside the bundle ($1)"
  rm -rf "$BUILD/selfcheck-data"
  HEARTH_DATA_DIR="$BUILD/selfcheck-data" HEARTH_DEV_PASSWORD="selfcheck-only" \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HOME="$BUILD/selfcheck-data/hf-home" \
    "$RES/python/bin/python3" - "$RES" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import mlx.core as mx
assert mx.metal.is_available(), "Metal GPU not available to the bundled MLX"
mx.eval(mx.ones(4) * 2)                          # runs a Metal kernel under this runtime/signature
import mlx_lm.server, mlx_audio.tts.utils, mlx_audio.stt.utils   # noqa: F401
import spacy
spacy.load("en_core_web_sm")                     # bundled; must not try to download
from misaki import en                            # noqa: F401
from app.voice import mlx_available, use_bundled_espeak
assert mlx_available(), "voice stack not importable"
assert use_bundled_espeak(), "bundled eSpeak NG library not found"
from phonemizer.backend.espeak.wrapper import EspeakWrapper
EspeakWrapper()                                  # loads the bundled dylib
from app.main import create_app
create_app()
print("ok")
PY
  rm -rf "$BUILD/selfcheck-data"
}
selfcheck "unsigned"
find "$APP" -name "__pycache__" -type d -prune -exec rm -rf {} +
# Precompile once, before signing: the signed bundle is never written to at run time.
"$RES/python/bin/python3" -m compileall -q -j 0 --invalidation-mode unchecked-hash "$RES" >/dev/null

if [ -n "${APP_SIGN_ID:-}" ]; then
  echo "==> Signing (hardened runtime)"
  /usr/bin/security find-identity -v -p codesigning | grep -qF "$APP_SIGN_ID" || { echo "APP_SIGN_ID not found in your keychain"; exit 1; }
  ENT="$HERE/entitlements.plist"
  find "$APP" -type f \( -perm -u+x -o -name "*.so" -o -name "*.dylib" \) -print0 | while IFS= read -r -d '' f; do
    if file "$f" | grep -q "Mach-O"; then /usr/bin/codesign --force --options runtime --timestamp --entitlements "$ENT" -s "$APP_SIGN_ID" "$f"; fi
  done
  /usr/bin/codesign --force --options runtime --timestamp --entitlements "$ENT" -s "$APP_SIGN_ID" "$APP"
  /usr/bin/codesign --verify --deep --strict --verbose=2 "$APP"
  selfcheck "signed, hardened runtime"
  /usr/bin/codesign --verify --deep --strict "$APP"   # the self-check must not have modified the bundle
fi

if [ -n "${APP_SIGN_ID:-}" ] && [ -n "${NOTARY_PROFILE:-}" ]; then
  echo "==> Notarizing the app (so it also works offline once copied out of the disk image)"
  /usr/bin/ditto -c -k --keepParent "$APP" "$BUILD/Hearth-app.zip"
  /usr/bin/xcrun notarytool submit "$BUILD/Hearth-app.zip" --keychain-profile "$NOTARY_PROFILE" --wait
  /usr/bin/xcrun stapler staple "$APP"
  rm -f "$BUILD/Hearth-app.zip"
fi

echo "==> Disk image"
DMG="$BUILD/Hearth-$VERSION.dmg"
DMGROOT="$BUILD/dmg"; RW="$BUILD/Hearth-rw.dmg"; VOL="Hearth"
rm -rf "$DMGROOT" "$RW"; mkdir -p "$DMGROOT/.background"
cp -R "$APP" "$DMGROOT/Hearth.app"
ln -s /Applications "$DMGROOT/Applications"
if /usr/bin/tiffutil -cathidpicheck "$HERE/assets/dmg-background.png" "$HERE/assets/dmg-background@2x.png" -out "$DMGROOT/.background/background.tiff" 2>/dev/null; then
  BG="background.tiff"
else
  cp "$HERE/assets/dmg-background.png" "$DMGROOT/.background/background.png"; BG="background.png"
fi
cp "$HERE/assets/AppIcon.icns" "$DMGROOT/.VolumeIcon.icns"
/usr/bin/hdiutil detach "/Volumes/$VOL" >/dev/null 2>&1 || true
/usr/bin/hdiutil create -volname "$VOL" -srcfolder "$DMGROOT" -fs HFS+ -format UDRW -ov "$RW" >/dev/null
ATTACH="$(/usr/bin/hdiutil attach -readwrite -noverify -noautoopen "$RW")"
DEV="$(echo "$ATTACH" | grep -E '^/dev/' | head -1 | awk '{print $1}')"
/usr/bin/SetFile -a C "/Volumes/$VOL" 2>/dev/null || true      # use the custom volume icon
# Window layout is cosmetic: if Finder scripting is not allowed, the disk image is still correct.
# (The first run may show "Terminal wants to control Finder": click OK.)
/usr/bin/osascript >/dev/null 2>&1 <<OSA || echo "   (window layout skipped; Finder automation not permitted)"
tell application "Finder"
  tell disk "$VOL"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {200, 120, 860, 520}
    set theViewOptions to the icon view options of container window
    set arrangement of theViewOptions to not arranged
    set icon size of theViewOptions to 128
    set text size of theViewOptions to 13
    set background picture of theViewOptions to file ".background:$BG"
    set position of item "Hearth.app" of container window to {165, 190}
    set position of item "Applications" of container window to {495, 190}
    close
    open
    update without registering applications
    delay 2
    close
  end tell
end tell
OSA
sync; sleep 1
/usr/bin/hdiutil detach "$DEV" >/dev/null || { sleep 3; /usr/bin/hdiutil detach "$DEV" -force >/dev/null; }
/usr/bin/hdiutil convert "$RW" -format UDZO -imagekey zlib-level=9 -ov -o "$DMG" >/dev/null
rm -f "$RW"
if [ -n "${APP_SIGN_ID:-}" ]; then
  /usr/bin/codesign --force --timestamp -s "$APP_SIGN_ID" "$DMG"
  if [ -n "${NOTARY_PROFILE:-}" ]; then
    /usr/bin/xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
    /usr/bin/xcrun stapler staple "$DMG"
    /usr/bin/xcrun stapler validate "$DMG"
    /usr/sbin/spctl --assess --type open --context context:primary-signature -v "$DMG"
  fi
fi
OUTPUTS="$DMG"

if [ "${MAKE_PKG:-0}" = 1 ]; then
  echo "==> Package"
  # Non-relocatable, so an upgrade always replaces /Applications/Hearth.app and never some stray copy.
  /usr/bin/pkgbuild --analyze --root "$STAGE" "$BUILD/component.plist" >/dev/null
  /usr/libexec/PlistBuddy -c "Set :0:BundleIsRelocatable false" "$BUILD/component.plist"
  OUT="$BUILD/Hearth-$VERSION.pkg"
  /usr/bin/pkgbuild --root "$STAGE" --component-plist "$BUILD/component.plist" \
    --identifier com.hearth.companion.pkg --version "$VERSION" \
    --install-location /Applications --scripts "$HERE/scripts" "$OUT.unsigned"
  if [ -n "${INSTALLER_SIGN_ID:-}" ]; then
    /usr/bin/productsign --sign "$INSTALLER_SIGN_ID" "$OUT.unsigned" "$OUT" && rm "$OUT.unsigned"
    if [ -n "${NOTARY_PROFILE:-}" ]; then
      /usr/bin/xcrun notarytool submit "$OUT" --keychain-profile "$NOTARY_PROFILE" --wait
      /usr/bin/xcrun stapler staple "$OUT"
      /usr/bin/xcrun stapler validate "$OUT"
      /usr/sbin/spctl --assess --type install -v "$OUT"
    fi
  else
    mv "$OUT.unsigned" "$OUT"
  fi
  OUTPUTS="$OUTPUTS
$OUT"
fi
echo
echo "Built:"
echo "$OUTPUTS"
