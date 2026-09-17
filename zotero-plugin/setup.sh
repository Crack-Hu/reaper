#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Always build the XPI first (before checking Zotero) ──
cd "$SCRIPT_DIR"
rm -f reaper-for-zotero.xpi

if [ ! -f manifest.json ] || [ ! -f bootstrap.js ] || [ ! -f prefs.js ] || [ ! -d content ]; then
    echo "Error: missing required files for XPI (manifest.json, bootstrap.js, prefs.js, content/)"
    exit 1
fi

zip -r reaper-for-zotero.xpi manifest.json bootstrap.js prefs.js content/ \
    -x "*.DS_Store" "*.xpi" "*.sh" "_repack/*" > /dev/null
echo "Packed: $(du -h reaper-for-zotero.xpi | cut -f1)"
echo "  → $SCRIPT_DIR/reaper-for-zotero.xpi"
echo ""

# ── Now install if Zotero is present (non‑fatal if not) ──
echo "Looking for Zotero profile…"

# Zotero 9 的 profile 命名可能用 .default、.default-release、或裸 UUID
PROFILE=""
for p in ~/Library/Application\ Support/Zotero/Profiles/*.default* ~/Library/Application\ Support/Zotero/Profiles/*.release; do
  if [ -d "$p" ]; then PROFILE="$p"; break; fi
done

if [ -z "$PROFILE" ]; then
    echo "Warning: Zotero profile not found."
    echo "  The XPI was built at: $SCRIPT_DIR/reaper-for-zotero.xpi"
    echo "  Drag it into Zotero → Tools → Plugins to install manually."
    exit 0
fi
echo "Profile: $PROFILE"

# ── Ensure extensions directory exists ──
mkdir -p "$PROFILE/extensions"

# ── Clean old installations ──
rm -f "$PROFILE/extensions/reaper@github.io"
rm -f "$PROFILE/extensions/reaper@github.io.xpi"

# ── Pack XPI ──
cd "$SCRIPT_DIR"
rm -f reaper-for-zotero.xpi
if [ -f manifest.json ] && [ -f bootstrap.js ] && [ -f prefs.js ] && [ -d content ]; then
    zip -r reaper-for-zotero.xpi manifest.json bootstrap.js prefs.js content/ \
        -x "*.DS_Store" "*.xpi" "*.sh" "_repack/*" > /dev/null
    echo "Packed: $(du -h reaper-for-zotero.xpi | cut -f1)"
else
    echo "Error: missing required files for XPI (manifest.json, bootstrap.js, prefs.js, content/)"
    exit 1
fi

# ── Install ──
cp "$SCRIPT_DIR/reaper-for-zotero.xpi" "$PROFILE/extensions/reaper@github.io.xpi"
echo "Installed to $PROFILE/extensions/reaper@github.io.xpi"

# ── Verify ──
echo ""
echo "Contents of $(basename "$PROFILE")/extensions/:"
ls -la "$PROFILE/extensions/" 2>/dev/null | grep reaper || echo "  (not found — check ls output below)"
ls -la "$PROFILE/extensions/" 2>/dev/null || echo "  (extensions/ directory not created)"
