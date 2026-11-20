"""Committed shelf input fixtures, independent of installed shelf or live Git."""

import json
from pathlib import Path

from git_porcelain.testing import FakeWorktree

from taskloop.shelf_digest.artifact import PATH

ROOT = Path(__file__).resolve().parents[2]


def shelf_files(provenance: str = "a" * 40, *, stale: bool = False) -> dict[str, bytes]:
    files = {path: (ROOT / path).read_bytes() for path in (PATH, "pyproject.toml", "uv.lock")}
    delivered = json.loads(files[PATH])["source_commit"].encode()
    data = files[PATH].replace(delivered, provenance.encode())
    files[PATH] = data.replace(b'"0.9.0"', b'"0.8.0"') if stale else data
    return files


def write_shelf(tree: FakeWorktree, provenance: str = "a" * 40, *, stale: bool = False) -> None:
    for path, data in shelf_files(provenance, stale=stale).items():
        tree.write_file(path, data.decode())
