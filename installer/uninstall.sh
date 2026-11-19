#!/bin/bash
# Remove Hearth. By default your data (memories, notes, settings, models, looks) is KEPT.
#   uninstall.sh                 remove the app and its background service, keep data
#   uninstall.sh --erase-data    also delete all Hearth data (asks you to type ERASE)
set -u
SUPPORT="$HOME/Library/Application Support/Hearth"
LABELS="com.hearth.local com.hearth.llm"
ERASE=0; [ "${1:-}" = "--erase-data" ] && ERASE=1

if [ "$ERASE" = 1 ]; then
  printf 'This permanently deletes everything Hearth has stored on this Mac. Type ERASE to continue: '
  read -r ANSWER; [ "$ANSWER" = "ERASE" ] || { echo "Cancelled."; exit 1; }
fi

for LABEL in $LABELS; do
  launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1
  rm -f "$HOME/Library/LaunchAgents/$LABEL.plist" "$SUPPORT/$LABEL.stamp" "$SUPPORT/service.stamp"
done
[ -d /Applications/Hearth.app ] && { rm -rf /Applications/Hearth.app 2>/dev/null || sudo rm -rf /Applications/Hearth.app; }
sudo pkgutil --forget com.hearth.companion.pkg >/dev/null 2>&1

if [ "$ERASE" = 1 ]; then
  rm -rf "$SUPPORT" "$HOME/Library/Logs/Hearth"
  echo "Hearth and all of its data were deleted. (Deletion on an SSD is logical; for a guarantee, rely on FileVault.)"
else
  echo "Hearth was removed. Your data (including the downloaded models in data/models) is still in: $SUPPORT"
fi
echo "If Hearth is still in your Dock, right-click it > Options > Remove from Dock."
