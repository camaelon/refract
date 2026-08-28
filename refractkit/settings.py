"""Load an optional per-deck settings.toml (stdlib tomllib, no dependencies)."""

from __future__ import annotations

import os
import sys
import tomllib


def load_settings(deck_dir: str) -> dict:
    """Return the parsed settings.toml from the deck root, or {} if absent/invalid."""
    path = os.path.join(deck_dir, "settings.toml")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        print(f"warning: could not read {path}: {e}", file=sys.stderr)
        return {}
