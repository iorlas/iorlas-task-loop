"""Set the "version" of a plugin.json / marketplace.json text without reformatting the rest of the file."""

from __future__ import annotations

import re


class NoVersionError(Exception):
    """The text has no version field to set."""


def set_json_version(text: str, new: str, after: int = 0) -> str:
    """`text` with the first "version" at or after offset `after` set to `new`, everything else byte-for-byte as it was."""
    m = re.compile(r'("version"\s*:\s*")(?:[^"\\]|\\.)*(")').search(text, after)
    if not m:
        msg = "no version field to set"
        raise NoVersionError(msg)
    return text[: m.start()] + m.group(1) + new + m.group(2) + text[m.end() :]


def entry_offset(text: str, name: str) -> int | None:
    """Where the plugin entry called `name` ends its "name" field (the offset to pass to set_json_version), None when there is none."""
    m = re.search(rf'"name"\s*:\s*"{re.escape(name)}"', text)
    return m.end() if m else None
