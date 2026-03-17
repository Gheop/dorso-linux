#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOCALES_DIR="$SCRIPT_DIR/../locales"

for po in "$LOCALES_DIR"/*/LC_MESSAGES/dorso.po; do
    dir="$(dirname "$po")"
    msgfmt "$po" -o "$dir/dorso.mo"
done

echo "All .mo files compiled."
