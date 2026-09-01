"""Load an optional per-deck settings.toml (stdlib tomllib, no dependencies)."""

from __future__ import annotations

import os
import sys
import tomllib


def load_settings(deck_dir: str) -> dict:
    """Return the parsed settings.toml from the deck root, or {} if it is absent.

    A *present* but broken settings file is a hard error: silently falling back to defaults
    (no shader, wrong bullets, …) just produces a mangled deck and a very confusing bug —
    e.g. a duplicate ``[table]`` makes tomllib reject the whole file. So we stop loudly and
    point at the exact problem instead."""
    path = os.path.join(deck_dir, "settings.toml")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        print(f"error: {path} is invalid — {e}", file=sys.stderr)
        raise SystemExit(1)
