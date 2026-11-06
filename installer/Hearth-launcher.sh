#!/bin/bash
# Hearth.app launcher: first-run setup -> (optional) model download consent -> start service -> open Brave.
# The companion itself runs as a per-user LaunchAgent bound to 127.0.0.1 only.
set -u

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RES="$APP_DIR/Resources"
PY="$RES/python/bin/python3"
SUPPORT="$HOME/Library/Application Support/Hearth"
DATA="$SUPPORT/data"
LOGS="$HOME/Library/Logs/Hearth"
PORT="${HEARTH_PORT:-4173}"
URL="http://127.0.0.1:$PORT/"
LABEL="com.hearth.local"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_NUM="$(id -u)"

say() { /usr/bin/osascript -e "display dialog \"$1\" with title \"Hearth\" buttons {\"OK\"} default button \"OK\" with icon caution" >/dev/null 2>&1; }

# Must run from Applications: from a disk image or Downloads macOS runs a temporary copy, and the
# background service would be left pointing at a path that disappears.
case "$APP_DIR" in
  /Applications/*|"$HOME"/Applications/*) ;;
  *) say "Please drag Hearth into the Applications folder first, then open it from there."; exit 0 ;;
esac

mkdir -p "$DATA" "$LOGS" "$HOME/Library/LaunchAgents"
chmod 700 "$SUPPORT" "$DATA"

if [ ! -x "$PY" ]; then say "Hearth's runtime is missing. Please reinstall Hearth."; exit 1; fi

# --- 1. first run: choose a password (typed into a macOS dialog; passed on stdin, never argv) ---
if [ ! -f "$DATA/auth.json" ]; then
  while true; do
    P1="$(/usr/bin/osascript -e 'text returned of (display dialog "Welcome to Hearth.\n\nChoose a password (8+ characters). You will use it to open the memory shelf." default answer "" with hidden answer with title "Hearth" buttons {"Cancel","OK"} default button "OK" with icon note)' 2>/dev/null)" || exit 0
    P2="$(/usr/bin/osascript -e 'text returned of (display dialog "Type the password again to confirm." default answer "" with hidden answer with title "Hearth" buttons {"Cancel","OK"} default button "OK" with icon note)' 2>/dev/null)" || exit 0
    if [ "$P1" != "$P2" ]; then say "Those did not match. Let's try again."; continue; fi
    if [ "${#P1}" -lt 8 ]; then say "Please choose a password with at least 8 characters."; continue; fi
    if printf '%s\n' "$P1" | "$PY" "$RES/tools/set_password.py" --data-dir "$DATA" >>"$LOGS/setup.log" 2>&1; then break; fi
    say "Hearth could not save the password. Details are in ~/Library/Logs/Hearth/setup.log."; exit 1
  done
  unset P1 P2
fi

# --- 2. models: ask once, only when something pinned is missing; this is the only use of the internet ---
PENDING="$("$PY" "$RES/tools/model_manager.py" --data-dir "$DATA" pending 2>/dev/null || true)"
if [ -n "$PENDING" ] && [ ! -f "$DATA/models/.declined" ]; then
  GB="$(awk -v b="$PENDING" 'BEGIN{printf "%.1f", b/1073741824}')"
  CHOICE="$(/usr/bin/osascript -e "button returned of (display dialog \"Hearth needs to download its language and voice models (about $GB GB). This is the only time Hearth uses the internet.\" with title \"Hearth\" buttons {\"Not now\", \"Download\"} default button \"Download\" with icon note)" 2>/dev/null || echo "Not now")"
  if [ "$CHOICE" = "Download" ]; then
    nohup "$PY" "$RES/tools/model_manager.py" --data-dir "$DATA" ensure --accept >>"$LOGS/models.log" 2>&1 &
    /usr/bin/osascript -e 'display notification "Downloading models in the background." with title "Hearth"' >/dev/null 2>&1
  fi
fi

# --- 3. service: install/refresh the per-user LaunchAgent (loopback only) ---
NEW_PLIST="$(mktemp)"
sed -e "s|@PYTHON@|$PY|g" -e "s|@RES@|$RES|g" -e "s|@DATA@|$DATA|g" \
    -e "s|@LOGS@|$LOGS|g" -e "s|@PORT@|$PORT|g" -e "s|@LABEL@|$LABEL|g" \
    "$RES/launchd/com.hearth.local.plist.template" >"$NEW_PLIST"
LOADED=1; launchctl print "gui/$UID_NUM/$LABEL" >/dev/null 2>&1 || LOADED=0
STAMP_FILE="$SUPPORT/service.stamp"
STAMP="$(cat "$RES/VERSION" 2>/dev/null)|$RES"
STAMP_OK=0; [ "$(cat "$STAMP_FILE" 2>/dev/null)" = "$STAMP" ] && STAMP_OK=1
# (Re)start when: nothing loaded, the plist changed, or this is a different build than the running one
# (dragging a new Hearth.app over the old one must not keep running the old code).
if [ ! -f "$PLIST" ] || ! cmp -s "$NEW_PLIST" "$PLIST" || [ "$LOADED" = 0 ] || [ "$STAMP_OK" = 0 ]; then
  launchctl bootout "gui/$UID_NUM/$LABEL" >/dev/null 2>&1
  mv "$NEW_PLIST" "$PLIST"; chmod 644 "$PLIST"
  launchctl bootstrap "gui/$UID_NUM" "$PLIST" >>"$LOGS/launch.log" 2>&1
  printf '%s' "$STAMP" >"$STAMP_FILE"
else
  rm -f "$NEW_PLIST"
fi

# --- 4. wait until the service answers ---
for _ in $(seq 1 40); do
  if /usr/bin/curl -fsS --max-time 1 "${URL}healthz" >/dev/null 2>&1; then READY=1; break; fi
  sleep 0.75
done
if [ "${READY:-0}" != 1 ]; then say "Hearth did not start. Details are in ~/Library/Logs/Hearth."; exit 1; fi

# --- 5a. once: offer to keep Hearth in the Dock ---
if [ ! -f "$SUPPORT/.dock-offered" ]; then
  touch "$SUPPORT/.dock-offered"
  DOCKCHOICE="$(/usr/bin/osascript -e 'button returned of (display dialog "Keep Hearth in your Dock so it is one click away?" with title "Hearth" buttons {"No thanks", "Add to Dock"} default button "Add to Dock" with icon note)' 2>/dev/null || echo "No thanks")"
  if [ "$DOCKCHOICE" = "Add to Dock" ] && ! /usr/bin/defaults read com.apple.dock persistent-apps 2>/dev/null | /usr/bin/grep -q "Hearth.app"; then
    /usr/bin/defaults write com.apple.dock persistent-apps -array-add \
      "<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key><string>$APP_DIR</string><key>_CFURLStringType</key><integer>0</integer></dict></dict></dict>" \
      && /usr/bin/killall Dock >/dev/null 2>&1
  fi
fi

# --- 5. open in Brave (Hearth is designed for Brave; no other browser is used) ---
if ! /usr/bin/open -a "Brave Browser" "$URL" 2>/dev/null; then
  say "Hearth opens in Brave, which was not found. Please install Brave, then open Hearth again."
  exit 1
fi
