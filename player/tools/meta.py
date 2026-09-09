#!/usr/bin/env python3
"""What may be written on a `::` line.

Run by refractplayer's editor, to offer it while one is being typed.

    python3 player/tools/meta.py --list

The vocabulary is refractkit's, not a copy of it — see refractkit/meta.py. A deck directory
is not needed and not asked for: the `::` grammar belongs to refract, and is the same for
every deck.
"""

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
try:
    from refractkit import meta
except ImportError:  # pragma: no cover - only when the script is copied out of the repo
    sys.stderr.write(f"meta.py: cannot import refractkit from {_ROOT}\n")
    raise


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--list", action="store_true", help="print the vocabulary as JSON")
    args = ap.parse_args()
    if not args.list:
        ap.error("give --list")
    out = {"ok": True}
    out.update(meta.vocabulary())
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
