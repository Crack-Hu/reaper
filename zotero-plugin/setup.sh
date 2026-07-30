#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

PROFILE=$(ls -d ~/Library/Application\ Support/Zotero/Profiles/*.default 2>/dev/null | head -1)
if [ -z "$PROFILE" ]; then
    echo "Error: Zotero profile not found."
    exit 1
fi
echo "Profile: $PROFILE"

# ── Clean old installations ──
rm -f "$PROFILE/extensions/reaper@github.io"
rm -f "$PROFILE/extensions/reaper@github.io.xpi"
rm -f "$PROFILE/extensions.json"
rm -f "$PROFILE/extensions.ini"
rm -f "$PROFILE/extensions.sqlite"

# ── Pack XPI ──
cd "$SCRIPT_DIR"
rm -f reaper-for-zotero.xpi
zip -r reaper-for-zotero.xpi manifest.json bootstrap.js prefs.js content/ -x "*.DS_Store" "*.xpi" "*.sh" "_repack/*" > /dev/null
echo "Packed: $(du -h reaper-for-zotero.xpi | cut -f1)"

# ── Install (XPI only, no proxy) ──
cp "$SCRIPT_DIR/reaper-for-zotero.xpi" "$PROFILE/extensions/reaper@github.io.xpi"
echo "Installed."

# ── Verify ──
echo ""
echo "Contents of $(basename "$PROFILE")/extensions/:"
ls -la "$PROFILE/extensions/" | grep reaper
