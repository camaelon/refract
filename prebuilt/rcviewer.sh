#!/usr/bin/env bash
# rcviewer, with its one non-system dependency supplied.
#
#   prebuilt/rcviewer.sh examples/deck/out 1600 900
#
# The prebuilt binary was linked against Homebrew's glfw and asks for it by absolute path:
#
#   Library not loaded: /opt/homebrew/opt/glfw/lib/libglfw.3.dylib
#
# On a machine without `brew install glfw` that is fatal, and the message points at a path
# rather than at the missing formula. Everything else rcviewer needs is a macOS framework.
#
# So a copy of glfw lives in prebuilt/lib and this script points dyld at it.
# DYLD_FALLBACK_LIBRARY_PATH is consulted by leaf name *only when the absolute path fails*,
# so a real Homebrew glfw still wins if one is installed, and the binary itself is untouched —
# no install_name_tool, no broken code signature.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HERE/rcviewer"
LIB="$HERE/lib"

[[ -x "$BIN" ]] || { echo "rcviewer not found at $BIN" >&2; exit 1; }
if [[ ! -f "$LIB/libglfw.3.dylib" && ! -f /opt/homebrew/opt/glfw/lib/libglfw.3.dylib ]]; then
  echo "no glfw: expected $LIB/libglfw.3.dylib or a Homebrew install" >&2
  echo "  either restore prebuilt/lib or run: brew install glfw" >&2
  exit 1
fi

export DYLD_FALLBACK_LIBRARY_PATH="$LIB${DYLD_FALLBACK_LIBRARY_PATH:+:$DYLD_FALLBACK_LIBRARY_PATH}"
exec "$BIN" "$@"
