#!/bin/sh
# Install dorso XDG autostart entry
set -e

DESKTOP_FILE="$(dirname "$0")/../data/dorso.desktop"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"

mkdir -p "$AUTOSTART_DIR"
cp "$DESKTOP_FILE" "$AUTOSTART_DIR/dorso.desktop"
echo "Autostart installed: $AUTOSTART_DIR/dorso.desktop"
echo "Dorso will start automatically on login."
