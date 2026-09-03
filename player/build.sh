#!/usr/bin/env bash
# Build refractplayer.
#
#   player/build.sh              configure (once) and build into player/build
#   RCX_DIR=… player/build.sh    against a specific players/cpp checkout
#
# The binary lands at player/build/refractplayer and is copied to prebuilt/.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
BUILD="$HERE/build"

RCX_DIR="${RCX_DIR:-}"
if [[ -z "$RCX_DIR" ]]; then
    for candidate in "$REPO/../remotecompose-experiments/players/cpp" "$REPO/../rcX"; do
        if [[ -f "$candidate/lib/rcplayer/CMakeLists.txt" ]]; then
            RCX_DIR="$(cd "$candidate" && pwd)"
            break
        fi
    done
fi
if [[ -z "$RCX_DIR" ]]; then
    echo "rcplayer not found. Clone remotecompose-experiments next to this repo," >&2
    echo "or run with RCX_DIR=/path/to/players/cpp" >&2
    exit 1
fi

# Skia is a ~400 MB fetch. If the rcX tree has already built once, reuse the archives it
# downloaded instead of pulling a second copy into this build tree.
FETCH_ARGS=()
if [[ -d "$RCX_DIR/build/_deps" ]]; then
    FETCH_ARGS+=("-DFETCHCONTENT_BASE_DIR=$RCX_DIR/build/_deps")
fi

cmake -B "$BUILD" -S "$HERE" -DRCX_DIR="$RCX_DIR" "${FETCH_ARGS[@]}" "$@"
cmake --build "$BUILD" -j"$(sysctl -n hw.ncpu 2>/dev/null || nproc)"

# Replace atomically rather than writing over the old binary. Overwriting a Mach-O
# in place that has already been executed leaves macOS holding a stale code-signature
# for that inode, and the next launch dies with SIGKILL and no message at all.
cp "$BUILD/refractplayer" "$REPO/prebuilt/.refractplayer.new"
mv -f "$REPO/prebuilt/.refractplayer.new" "$REPO/prebuilt/refractplayer"
echo "built $REPO/prebuilt/refractplayer"
