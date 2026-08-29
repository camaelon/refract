"""rcj — a self-contained, byte-identical Python implementation of the official
RemoteCompose JSON -> RC converter (androidx RemoteComposeJsonParser).

Goal: `convert(json_str)` must produce byte-for-byte identical output to the Java
reference parser, verified against the desktop oracle (oracle/oracle.sh).
"""

from __future__ import annotations

import json

from .parser import (
    NotImplementedComponent,
    RemoteComposeJsonParser,
    parse_api_level,
    parse_header_only,
)
from .writer import RemoteComposeWriter

__all__ = ["convert", "convert_doc", "unwrap", "NotImplementedComponent"]


def unwrap(doc: dict) -> dict:
    """Return the RemoteCompose document itself.

    Generation-library entries wrap the document under a `json` key alongside prose
    metadata (name/description/tags/data_schema); everything else is already a document.
    """
    if "root" not in doc and isinstance(doc.get("json"), dict):
        return doc["json"]
    return doc


def convert_doc(doc: dict, base_dir: str | None = None) -> bytes:
    """Convert an already-parsed JSON document (or library entry) to RC bytes.

    `base_dir` resolves relative paths in `resources.bitmaps`; without it only absolute
    paths and inline base64 work.
    """
    doc = unwrap(doc)
    tags = parse_header_only(doc)
    api_level = parse_api_level(doc)
    writer = RemoteComposeWriter(api_level, tags)
    parser = RemoteComposeJsonParser(writer, base_dir=base_dir)
    parser.parse(doc)
    return writer.encode_to_byte_array()


def convert(json_str: str, base_dir: str | None = None) -> bytes:
    """Convert a JSON document string to RC bytes (the canonical example path).

    `base_dir` resolves relative paths in `resources.bitmaps`.
    """
    doc = unwrap(json.loads(json_str))
    tags = parse_header_only(doc)
    api_level = parse_api_level(doc)
    writer = RemoteComposeWriter(api_level, tags)
    parser = RemoteComposeJsonParser(writer, base_dir=base_dir)
    parser.parse(doc)
    return writer.encode_to_byte_array()
