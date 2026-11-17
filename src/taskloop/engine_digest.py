"""The engine's identity: one digest of every installed file, so two results compare only when the same code produced them.

The digest is sha256 over the sorted `(path, hash)` pairs of every installed distribution's `RECORD`, leaving out each
`*.dist-info/` entry (it holds install-time files such as `direct_url.json` and the `RECORD` itself) and every path outside the
environment (those start with `..`: the `tl` script). A file with no recorded hash fails: the digest is never partial."""

import csv
import hashlib
from collections.abc import Iterable
from functools import cache
from importlib import metadata


class UnhashedFile(Exception):
    """An installed file has no hash in its distribution's `RECORD`, so the digest could not witness it."""


def engine_digest(files: Iterable[tuple[str, str | None]]) -> str:
    """The digest of `(path, hash)` pairs; a `None` hash raises `UnhashedFile`."""
    kept = sorted(each for each in files if ".dist-info/" not in each[0] and not each[0].startswith(".."))
    for path, digest in kept:
        if digest is None:
            raise UnhashedFile(path)
    return hashlib.sha256("\n".join(f"{path} {digest}" for path, digest in kept).encode("utf-8")).hexdigest()


def installed_files() -> Iterable[tuple[str, str | None]]:
    """Every file of every installed distribution with its recorded hash (`sha256=...`), read from its `RECORD`."""
    for distribution in metadata.distributions():
        record = distribution.read_text("RECORD")
        if record is None:
            raise UnhashedFile(f"{distribution.metadata['Name']}: no RECORD")
        for path, digest, _size in csv.reader(record.splitlines()):
            yield path, digest or None


@cache
def installed_digest() -> str:
    """The digest of this interpreter's environment: read once per process by the composition root."""
    return engine_digest(installed_files())
