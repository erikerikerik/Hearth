#!/bin/bash
# Hearth.app launcher: first-run setup -> model download consent -> start services -> open Brave.
#
# Two per-user LaunchAgents, both bound to 127.0.0.1 only:
#   com.hearth.local  the companion (UI, memory, Whisper + Kokoro speech) on :4173
#   com.hearth.llm    the local language model (mlx_lm.server) on :8081, installed only once its
#                     model snapshot has been downloaded and verified
#
#   Hearth                     normal click from the Dock / Applications
#   Hearth --download          (internal) consented background download, then refresh the services
set -u
export PYTHONDONTWRITEBYTECODE=1   # the signed app bundle is never written to (bytecode is precompiled)

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"          # …/Hearth.app/Contents
APP_BUNDLE="${APP_DIR%/Contents}"                     # …/Hearth.app
SELF="$APP_DIR/MacOS/$(basename "$0")"
RES="$APP_DIR/Resources"
PY="$RES/python/bin/python3"
MM="$RES/tools/model_manager.py"
SUPPORT="$HOME/Library/Application Support/Hearth"
DATA="$SUPPORT/data"
LOGS="$HOME/Library/Logs/Hearth"
PORT="${HEARTH_PORT:-4173}"
LLM_PORT=8081
URL="http://127.0.0.1:$PORT/"
LABEL="com.hearth.local"
LLM_LABEL="com.hearth.llm"
AGENTS="$HOME/Library/LaunchAgents"
UID_NUM="$(id -u)"
MODE="${1:-}"

say() { /usr/bin/osascript -e "display dialog \"$1\" with title \"Hearth\" buttons {\"OK\"} default button \"OK\" with icon caution" >/dev/null 2>&1; }
notify() { /usr/bin/osascript -e "display notification \"$1\" with title \"Hearth\"" >/dev/null 2>&1; }
http_ok() { /usr/bin/curl -fsS --max-time 1 --noproxy '*' "$1" >/dev/null 2>&1; }
mm() { HEARTH_DATA_DIR="$DATA" "$PY" "$MM" --data-dir "$DATA" "$@"; }

# Must run from Applications: from a disk image or Downloads macOS runs a temporary copy, and the
# background services would be left pointing at a path that disappears.
case "$APP_DIR" in
  /Applications/*|"$HOME"/Applications/*) ;;
  *) say "Please drag Hearth into the Applications folder first, then open it from there."; exit 0 ;;
esac

mkdir -p "$DATA" "$LOGS" "$AGENTS"
chmod 700 "$SUPPORT" "$DATA"

if [ ! -x "$PY" ]; then say "Hearth's runtime is missing. Please reinstall Hearth."; exit 1; fi

# Install or refresh one LaunchAgent from its template. Restarts it only when its plist changed,
# it is not loaded, or the build/models it runs are different from what it was started with.
install_agent() {  # label template stamp [model]
  local label="$1" template="$2" stamp="$3" model="${4:-}"
  local plist="$AGENTS/$label.plist" stamp_file="$SUPPORT/$label.stamp" new loaded=1
  new="$(mktemp)"
  sed -e "s|@PYTHON@|$PY|g" -e "s|@RES@|$RES|g" -e "s|@DATA@|$DATA|g" -e "s|@LOGS@|$LOGS|g" \
      -e "s|@PORT@|$PORT|g" -e "s|@LLM_PORT@|$LLM_PORT|g" -e "s|@LABEL@|$label|g" -e "s|@MODEL@|$model|g" \
      "$RES/launchd/$template" >"$new"
  launchctl print "gui/$UID_NUM/$label" >/dev/null 2>&1 || loaded=0
  if [ ! -f "$plist" ] || ! cmp -s "$new" "$plist" || [ "$loaded" = 0 ] || [ "$(cat "$stamp_file" 2>/dev/null)" != "$stamp" ]; then
    launchctl bootout "gui/$UID_NUM/$label" >/dev/null 2>&1
    mv "$new" "$plist"; chmod 644 "$plist"
    launchctl bootstrap "gui/$UID_NUM" "$plist" >>"$LOGS/launch.log" 2>&1
    printf '%s' "$stamp" >"$stamp_file"
    return 0
  fi
  rm -f "$new"
  return 1
}

remove_agent() {
  launchctl bootout "gui/$UID_NUM/$1" >/dev/null 2>&1
  rm -f "$AGENTS/$1.plist" "$SUPPORT/$1.stamp"
}

refresh_services() {
  # Restart the companion when the build or the installed models change, so it loads the new ones.
  local build models llm_model
  build="$(cat "$RES/VERSION" 2>/dev/null)|$RES"
  models="$(/usr/bin/shasum -a 256 "$DATA/models/installed.json" 2>/dev/null | awk '{print $1}')"
  install_agent "$LABEL" com.hearth.local.plist.template "$build|$models"
  llm_model="$(mm path llm 2>/dev/null)"
  LLM_STARTED=0
  if [ -n "$llm_model" ] && [ -d "$llm_model" ]; then
    install_agent "$LLM_LABEL" com.hearth.llm.plist.template "$build|$llm_model" "$llm_model" && LLM_STARTED=1
  else
    remove_agent "$LLM_LABEL"
  fi
}

# --- internal: consented background download, then pick up the new models ---
if [ "$MODE" = "--download" ]; then
  if mm ensure --accept; then
    refresh_services
    notify "Hearth's voice is ready. Reload the Hearth page in Brave to start talking."
  else
    notify "The model download stopped. Open Hearth again to resume it. Details: ~/Library/Logs/Hearth/models.log"
  fi
  exit 0
fi

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

# --- 2. models: ask whenever something pinned is still missing; this is the only use of the internet ---
if BUSY="$(mm downloading 2>/dev/null)"; then
  notify "Still downloading Hearth's voice and language models ($BUSY)."
else
  PENDING="$(mm pending 2>>"$LOGS/models.log" || true)"
  if [ -n "$PENDING" ]; then
    GB="$(awk -v b="$PENDING" 'BEGIN{printf "%.1f", b/1000000000}')"
    CHOICE="$(/usr/bin/osascript -e "button returned of (display dialog \"Hearth needs to download its voice and language models (about $GB GB) from Hugging Face. Each file is checked against a fingerprint built into Hearth before it is used.\n\nThis download is the only time Hearth uses the internet. Hearth can't listen or talk until it finishes.\" with title \"Hearth\" buttons {\"Not now\", \"Download\"} default button \"Download\" with icon note)" 2>/dev/null || echo "Not now")"
    if [ "$CHOICE" = "Download" ]; then
      nohup "$SELF" --download >>"$LOGS/models.log" 2>&1 &
      notify "Downloading models in the background. Hearth will tell you when its voice is ready."
    fi
  fi
fi

# --- 3. services (loopback only) ---
refresh_services

# --- 4. wait until the companion answers ---
for _ in $(seq 1 40); do
  if http_ok "${URL}healthz"; then READY=1; break; fi
  sleep 0.75
done
if [ "${READY:-0}" != 1 ]; then say "Hearth did not start. Details are in ~/Library/Logs/Hearth."; exit 1; fi

# If the language model was just (re)started, give it up to two minutes to load so the first reply is real.
if [ "$LLM_STARTED" = 1 ]; then
  notify "Hearth is waking up…"
  for _ in $(seq 1 120); do http_ok "http://127.0.0.1:$LLM_PORT/v1/models" && break; sleep 1; done
fi

# --- 5a. once: offer to keep Hearth in the Dock ---
if [ ! -f "$SUPPORT/.dock-offered" ]; then
  touch "$SUPPORT/.dock-offered"
  DOCKCHOICE="$(/usr/bin/osascript -e 'button returned of (display dialog "Keep Hearth in your Dock so it is one click away?" with title "Hearth" buttons {"No thanks", "Add to Dock"} default button "Add to Dock" with icon note)' 2>/dev/null || echo "No thanks")"
  if [ "$DOCKCHOICE" = "Add to Dock" ] && ! /usr/bin/defaults read com.apple.dock persistent-apps 2>/dev/null | /usr/bin/grep -q "Hearth.app"; then
    /usr/bin/defaults write com.apple.dock persistent-apps -array-add \
      "<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key><string>$APP_BUNDLE</string><key>_CFURLStringType</key><integer>0</integer></dict></dict></dict>" \
      && /usr/bin/killall Dock >/dev/null 2>&1
  fi
fi

# --- 5. open in Brave (Hearth is designed for Brave; no other browser is used) ---
if ! /usr/bin/open -a "Brave Browser" "$URL" 2>/dev/null; then
  say "Hearth opens in Brave, which was not found. Please install Brave, then open Hearth again."
  exit 1
fi
