#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EXT_SRC="$SCRIPT_DIR/../gnome-extension"
EXT_DIR="$HOME/.local/share/gnome-shell/extensions/dorso-overlay@dorso-linux"

mkdir -p "$EXT_DIR"
cp "$EXT_SRC"/metadata.json "$EXT_SRC"/extension.js "$EXT_DIR/"

echo "Extension installed to $EXT_DIR"
echo "Restart GNOME Shell (log out/in on Wayland) then enable:"
echo "  gnome-extensions enable dorso-overlay@dorso-linux"
