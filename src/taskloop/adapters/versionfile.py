"""Set the "version" of a plugin.json / marketplace.json text without reformatting the rest of the file."""
import re


class NoVersion(Exception):
    """The text has no version field to set."""


def set_version(text: str, new: str, after: int = 0) -> str:
    """The first "version" at or after offset `after` set to `new`, the rest of the file as it was."""
    m = re.compile(r'("version"\s*:\s*")[^"]*(")').search(text, after)
    if not m:
        raise NoVersion("no version field to bump")
    return text[:m.start()] + m.group(1) + new + m.group(2) + text[m.end():]


def entry_offset(text: str, name: str) -> int | None:
    """Where the plugin entry called `name` ends its "name" field (the offset to pass to set_version), None when there is none."""
    m = re.search(rf'"name"\s*:\s*"{re.escape(name)}"', text)
    return m.end() if m else None
