"""Reading `out/deck.json`, for the tools that act on a built deck.

Three of the player's tools — reorder, build, slide — start from the same place: an `out/`
directory, the deck it belongs to, and the options that deck was built with. That is here so
they agree, and in particular so they all replay a build the same way.
"""

from __future__ import annotations

import json
import os


class NotADeck(Exception):
    """The directory given is not a built deck, and nothing sensible can be done with it."""


def load(out_dir: str) -> dict:
    """The manifest in ``out_dir``. Raises :class:`NotADeck` when there is none."""
    path = os.path.join(out_dir, "deck.json")
    if not os.path.isfile(path):
        raise NotADeck(f"no deck.json in {out_dir}")
    with open(path) as f:
        return json.load(f)


def source_dir(out_dir: str, deck: dict) -> str:
    """The directory the slides' ``src`` paths are relative to — where the markdown lives."""
    return os.path.abspath(os.path.join(out_dir, deck.get("deck_dir", "..")))


# What a build produces and may replace. A file outside this set is none of its business.
BUILT_EXTS = (".rc", ".notes", ".mp4", ".mov", ".m4v", ".webm")


def outputs(out_dir: str) -> dict:
    """Every generated file under ``out/``, with its modification time.

    Taken either side of a build, the difference is exactly what was rebuilt. That is worth
    knowing twice over: it is the number the build panel shows, and it is what lets the player
    throw away only the slide stills that actually changed instead of all of them.
    """
    found = {}
    for directory in (out_dir, os.path.join(out_dir, "media")):
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        for name in names:
            if not name.endswith(BUILT_EXTS):
                continue
            path = os.path.join(directory, name)
            try:
                found[os.path.relpath(path, out_dir)] = os.stat(path).st_mtime_ns
            except OSError:
                pass
    return found


def changed_since(before: dict, out_dir: str) -> list[str]:
    """The outputs that a build has just written or replaced, newest state against `before`."""
    after = outputs(out_dir)
    return sorted(name for name, stamp in after.items() if before.get(name) != stamp)


def build_args(deck: dict, **overrides) -> list[str]:
    """The refract options this deck was built with, to build it the same way again.

    ``--transitions`` is a command-line flag with nothing in the deck to say it was given, so
    a rebuild that forgot it would silently strip every transition out of the deck the first
    time a slide was moved or edited. The size comes from the manifest for the same reason in
    reverse: a deck that set its size in settings.toml must not be resized by a rebuild.

    Keyword overrides (``transitions``, ``debug``, ``force``, ``keep_json``, ``width``,
    ``height``) take precedence, for a caller that is deliberately building it differently.
    """
    build = deck.get("build") or {}
    args = []
    for flag, key, source in (("--transitions", "transitions", build),
                              ("--debug", "debug", build),
                              ("--force", "force", {}),
                              ("--json", "keep_json", {})):
        value = overrides.get(key)
        if value is None:
            value = source.get(key, False)
        if value:
            args.append(flag)
    for key in ("width", "height"):
        value = overrides.get(key)
        if value is None:
            value = deck.get(key)
        if isinstance(value, int):
            args += [f"--{key}", str(value)]
    return args
