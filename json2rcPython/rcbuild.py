#!/usr/bin/env python3
"""rcbuild — compile RemoteCompose JSON documents into `.rc` binaries.

    tools/rcbuild.py samples/json/hello.json
    tools/rcbuild.py samples/json/                 # every .json in a directory
    tools/rcbuild.py samples/json/ -o build/       # somewhere other than alongside
    tools/rcbuild.py --check samples/json/         # compile but write nothing
    tools/rcbuild.py --verify samples/json/        # is each committed .rc still its source?

Pure standard library — no pip install, no virtualenv, Python 3.8+. Bitmaps referenced by
a document are resolved relative to that document's own directory.

A `.rc` file is the wire format every RemoteCompose player reads: the Android player, the
web player in `web/`, and the C++ player. Compiling is the whole build step; there is no
packaging stage and no manifest.

`--verify` exists because a few `.rc` files are committed. `.rc` is gitignored as build
output, but a sample that demonstrates a player without the toolchain has to ship prebuilt,
and those are force-added. A committed binary drifts the moment someone edits the `.json`
and does not rebuild — and nothing about the repository would look wrong. `--verify`
recompiles each source and compares, so the drift is a build failure instead of a surprise
for whoever opens the stale file.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rcj import NotImplementedComponent, convert  # noqa: E402

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"

# Directories that only ever hold generated or third-party files. A path named explicitly on
# the command line is still compiled — this prunes the recursive walk, nothing else.
SKIP_DIRS = {"build", ".gradle", ".idea", "node_modules", "out", "__pycache__", "venv"}


def colour(enabled: bool):
    if enabled:
        return GREEN, RED, YELLOW, DIM, RESET
    return "", "", "", "", ""


def collect(paths: list[str]) -> list[str]:
    """Expand directories to the .json files under them, recursively, in sorted order.

    Recursive on purpose. Samples are grouped in subdirectories — one per chart set, one per
    generated document with its textures — so a non-recursive walk made
    `rcbuild.py samples/json/` compile the two loose files at the top and silently skip
    every real sample beneath. It reported success while doing almost nothing.
    """
    out: list[str] = []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                # Prune generated trees. Not every .json is a document: an Android build
                # leaves Gradle's own under app/build, and walking into them made
                # `rcbuild.py apps/` try to compile navigation.json and merge manifests.
                dirs[:] = sorted(d for d in dirs
                                 if d not in SKIP_DIRS and not d.startswith("."))
                out.extend(os.path.join(root, f) for f in sorted(files)
                           if f.endswith(".json"))
        else:
            out.append(p)                       # named explicitly: compile it regardless
    return out


_TRACKED: set[str] | None = None


def tracked(path: str) -> bool:
    """Is this path committed? Cached, and false everywhere if git is not available.

    Only an annotation: an untracked `.rc` that has gone stale is a local inconvenience,
    a tracked one ships to everybody. Both are reported; this says which is which.
    """
    global _TRACKED
    if _TRACKED is None:
        here = os.path.dirname(os.path.abspath(__file__))
        try:
            root = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                  capture_output=True, text=True, timeout=30, cwd=here)
            base = root.stdout.strip()
            # From the repository root, not from here: `git ls-files` is limited to its
            # working directory, so running it in tools/ listed a dozen files and reported
            # every sample as untracked.
            out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, text=True,
                                 timeout=30, cwd=base or here)
            _TRACKED = {os.path.realpath(os.path.join(base, p))
                        for p in out.stdout.split("\0") if p}
        except Exception:                       # not a repo, no git, whatever — annotate nothing
            _TRACKED = set()
    return os.path.realpath(path) in _TRACKED


def verify_one(src: str, out_dir: str | None, data: bytes) -> tuple[bool, str]:
    """Compare an already-built `.rc` against what `src` compiles to now."""
    dst_dir = out_dir if out_dir else os.path.dirname(os.path.abspath(src))
    dst = os.path.join(dst_dir, os.path.basename(src)[:-5] + ".rc")
    if not os.path.exists(dst):
        # Not a failure: most sources have no committed binary, and demanding one would
        # turn this into a build step rather than a check.
        return True, "no .rc beside it"
    with open(dst, "rb") as f:
        existing = f.read()
    mark = " [tracked]" if tracked(dst) else ""
    if existing == data:
        return True, f"{len(data)} bytes, matches{mark}"
    # Same length, different bytes is the common case — a colour or a coordinate changed.
    # Quoting two identical numbers reads as a bug in the checker, so say what differs.
    if len(existing) == len(data):
        first = next(i for i, (a, b) in enumerate(zip(existing, data)) if a != b)
        detail = f"same length ({len(data)} bytes), first differing byte at {first}"
    else:
        detail = f"{len(existing)} bytes on disk, {len(data)} from the source"
    return False, f"STALE{mark}: {os.path.relpath(dst)} — {detail}; rebuild it"


def build_one(src: str, out_dir: str | None, check: bool,
              verify: bool = False) -> tuple[bool, str]:
    """Compile one document. Returns (ok, message)."""
    try:
        with open(src, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        return False, f"cannot read: {e.strerror}"

    try:
        # base_dir so `bitmaps` entries resolve next to the document that names them.
        data = convert(text, base_dir=os.path.dirname(os.path.abspath(src)))
    except NotImplementedComponent as e:
        # The converter names the command or modifier it does not implement. That message is
        # the useful part — do not flatten it into "failed".
        return False, f"unsupported: {e}"
    except Exception as e:  # noqa: BLE001 - a malformed document should not traceback
        return False, f"{type(e).__name__}: {e}"

    if verify:
        return verify_one(src, out_dir, data)

    if check:
        return True, f"{len(data)} bytes (not written)"

    dst_dir = out_dir if out_dir else os.path.dirname(os.path.abspath(src))
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, os.path.basename(src)[:-5] + ".rc")
    with open(dst, "wb") as f:
        f.write(data)
    return True, f"{len(data)} bytes -> {os.path.relpath(dst)}"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Compile RemoteCompose JSON to .rc",
        epilog="Exit status is non-zero if any document failed, so this is usable in CI.")
    ap.add_argument("paths", nargs="+", help=".json files, or directories containing them")
    ap.add_argument("-o", "--out", help="output directory (default: beside each source)")
    ap.add_argument("--check", action="store_true",
                    help="compile and report, but write nothing")
    ap.add_argument("--verify", action="store_true",
                    help="compare each existing .rc against its source; fail if stale")
    ap.add_argument("--quiet", "-q", action="store_true", help="only report failures")
    args = ap.parse_args()

    g, r, y, d, x = colour(sys.stdout.isatty())
    files = collect(args.paths)
    if not files:
        print("no .json files found", file=sys.stderr)
        return 2

    ok = 0
    failed: list[str] = []
    for src in files:
        good, msg = build_one(src, args.out, args.check, args.verify)
        name = os.path.relpath(src)
        if good:
            ok += 1
            if not args.quiet:
                print(f"  {g}ok{x}   {name:<44} {d}{msg}{x}")
        else:
            failed.append(name)
            print(f"  {r}FAIL{x} {name:<44} {msg}")

    total = len(files)
    verb = "verified" if args.verify else "compiled"
    if failed:
        bad = "stale" if args.verify else "failed"
        print(f"\n  {ok}/{total} {verb}, {r}{len(failed)} {bad}{x}")
        return 1
    print(f"\n  {g}{ok}/{total} {verb}{x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
