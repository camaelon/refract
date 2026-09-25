#!/bin/sh
#
# Install the open-source fonts the converted decks need.
#
# Refract resolves font families through the *system* font list, so a
# `family = "Instrument Serif"` in a theme TOML silently falls back to the
# deck's default font when that family is not installed. The layout comes out
# right and the letterforms come out wrong, which is easy to miss in a
# numeric pixel diff.
#
# All three fonts below are SIL Open Font License, pulled straight from the
# google/fonts repository.
#
#   Unbounded        examples/ads26 slide 5 title
#   Instrument Serif examples/ads26 slide 5 card captions
#   Roboto Mono      examples/ads26 slide 9 product label - this one is a
#                    SUBSTITUTE. The source deck uses Google Sans Mono, which
#                    is not publicly distributable.
#
# macOS installs into ~/Library/Fonts. On Linux, set DEST=~/.local/share/fonts
# and run fc-cache afterwards.

set -eu

DEST="${DEST:-$HOME/Library/Fonts}"
BASE="https://raw.githubusercontent.com/google/fonts/main/ofl"

mkdir -p "$DEST"

fetch() {
    url="$1"
    name="$2"
    if [ -f "$DEST/$name" ]; then
        echo "  already installed: $name"
        return
    fi
    echo "  installing: $name"
    curl -fsSL -o "$DEST/$name" "$url"
}

echo "Installing deck fonts into $DEST"
fetch "$BASE/unbounded/Unbounded%5Bwght%5D.ttf"            "Unbounded[wght].ttf"
fetch "$BASE/instrumentserif/InstrumentSerif-Regular.ttf"  "InstrumentSerif-Regular.ttf"
fetch "$BASE/instrumentserif/InstrumentSerif-Italic.ttf"   "InstrumentSerif-Italic.ttf"
fetch "$BASE/robotomono/RobotoMono%5Bwght%5D.ttf"          "RobotoMono[wght].ttf"
echo "Done."
