"""Incremental builds: telling what has to be regenerated from what can be left alone.

Compiling a slide to ``.rc`` means starting a JVM (``json2rc``), and a deck of forty slides
pays that on every build even when one word changed. This tracks, per output file, a
fingerprint of everything that went into it; an output whose fingerprint still matches is
left where it is.

The fingerprint is taken of the **generated JSON document**, not of the markdown. That is
the whole input to ``json2rc``, so if it is unchanged the ``.rc`` is necessarily unchanged,
and no reasoning is needed about which markdown edits reach which slide. It also means the
things that are *not* in the markdown are covered for free: a slide's page number and
progress bar are drawn into the document, so reordering a deck changes every slide's
document after the move and every one of them is rebuilt — which is exactly right, and would
have been easy to get wrong by fingerprinting the source text instead.
"""

from __future__ import annotations

import hashlib
import json
import os

CACHE_NAME = ".refract-cache.json"
# Bumped when the meaning of a fingerprint changes; an older cache is then ignored rather
# than trusted, so a format change can never leave stale .rc files behind.
CACHE_VERSION = 1


def referenced_files(doc) -> list[str]:
    """Absolute paths named anywhere in a document that exist on disk.

    ``json2rc`` inlines some of what a document points at — an ``image`` component embeds the
    file's bytes — so those files are part of the input even though their contents are not in
    the JSON. Everything refract puts in a document uses an absolute path (``resolve_include``
    makes them so), which is also the cheap test that keeps this from stat-ing every string in
    a document full of shader source.
    """
    found: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str) and node.startswith("/") and os.path.isfile(node):
            found.add(node)

    walk(doc)
    return sorted(found)


def file_digest(path: str) -> str:
    """SHA-256 of a file's contents, read in chunks so a large asset is not held in memory."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def doc_fingerprint(doc) -> str:
    """A document plus every file it inlines, as one hash.

    Keys are sorted so that a dict built in a different order is still recognised as the same
    document — otherwise an unrelated refactor in the renderer would rebuild the whole deck.
    """
    h = hashlib.sha256()
    h.update(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode())
    for path in referenced_files(doc):
        h.update(b"\0")
        h.update(os.path.basename(path).encode())
        h.update(file_digest(path).encode())
    return h.hexdigest()


def copy_fingerprint(path: str) -> str:
    """Size and modification time of a file that is copied rather than compiled.

    Copies are videos and prebuilt ``.rc`` binaries, which can be large and are not read by
    the build at all — hashing them would cost more than the copy it saves. mtime is the
    normal trade: a touched file is copied again, which is cheap and wrong in the safe
    direction."""
    try:
        st = os.stat(path)
    except OSError:
        return ""
    return f"{st.st_size}:{st.st_mtime_ns}"


def tool_stamp(path: str | None) -> str:
    """Identifies the compiler itself. A new ``json2rc`` can turn the same JSON into a
    different ``.rc``, and nothing in a document would say so — so the whole cache is dropped
    when the binary changes."""
    if not path or not os.path.exists(path):
        return "none"
    try:
        st = os.stat(path)
    except OSError:
        return "none"
    return f"{os.path.basename(path)}:{st.st_size}:{st.st_mtime_ns}"


class BuildCache:
    """What the last build produced, keyed by output path relative to ``out/``.

    Two dicts, deliberately: ``previous`` is what was read from disk and is only ever
    questioned, ``current`` is what this build vouches for and is what gets written. An
    output nobody vouches for is simply absent next time and gets rebuilt — which is the
    behaviour wanted when a conversion fails, since forgetting is always safe and remembering
    a failure is not.
    """

    def __init__(self, out_dir: str, stamp: str = "none"):
        self.out_dir = out_dir
        self.stamp = stamp
        self.previous: dict[str, str] = {}
        self.current: dict[str, str] = {}

    @property
    def path(self) -> str:
        return os.path.join(self.out_dir, CACHE_NAME)

    def rel(self, path: str) -> str:
        return os.path.relpath(os.path.abspath(path), os.path.abspath(self.out_dir))

    def load(self) -> "BuildCache":
        try:
            with open(self.path) as f:
                doc = json.load(f)
        except (OSError, ValueError):
            return self
        if doc.get("version") != CACHE_VERSION or doc.get("stamp") != self.stamp:
            return self          # a different format or a different compiler: trust none of it
        outputs = doc.get("outputs")
        if isinstance(outputs, dict):
            self.previous = {k: v for k, v in outputs.items() if isinstance(v, str)}
        return self

    def save(self) -> None:
        try:
            with open(self.path, "w") as f:
                json.dump({"version": CACHE_VERSION, "stamp": self.stamp,
                           "outputs": self.current}, f, indent=2, sort_keys=True)
        except OSError:
            pass                 # a cache that cannot be written costs speed, not correctness

    def fresh(self, path: str, fingerprint: str) -> bool:
        """True when this exact input produced ``path`` last time and the file is still there.

        The existence check is not paranoia: a deleted or hand-edited output has to come
        back, and that is the only signal there is."""
        return self.previous.get(self.rel(path)) == fingerprint and os.path.exists(path)

    def keep(self, path: str, fingerprint: str) -> None:
        self.current[self.rel(path)] = fingerprint

    def forget(self, path: str) -> None:
        self.current.pop(self.rel(path), None)


def prune(managed: list[tuple[str, tuple[str, ...]]], keep: set[str]) -> list[str]:
    """Delete generated files nobody claimed this build, and return what was removed.

    Renaming or deleting a slide leaves its old ``.rc`` behind, and the player would go on
    showing it — so the sweep still happens, it just happens at the end against the list of
    what was actually produced rather than at the start against everything.

    ``managed`` is (directory, extensions) pairs: only files refract generates are ever
    considered, so nothing a user dropped into ``out/`` is at risk.
    """
    removed = []
    for directory, exts in managed:
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        for name in names:
            if not name.endswith(exts):
                continue
            path = os.path.join(directory, name)
            if os.path.abspath(path) in keep or not os.path.isfile(path):
                continue
            try:
                os.remove(path)
                removed.append(path)
            except OSError:
                pass
    return removed
