"""The engine digest witnesses the installed files, is stable, and refuses an unhashed file."""

import re

import pytest

from taskloop.engine_digest import UnhashedFile, engine_digest, installed_digest

FILES = [("pkg/a.py", "sha256=aa"), ("pkg/b.py", "sha256=bb")]


def test_digest_ignores_order_and_install_time_files() -> None:
    noise = [("pkg-1.dist-info/direct_url.json", "sha256=x"), ("../../bin/tl", None)]
    assert engine_digest([*FILES, *noise]) == engine_digest(reversed(FILES))


def test_digest_changes_with_a_file_hash_or_path() -> None:
    base = engine_digest(FILES)
    assert engine_digest([("pkg/a.py", "sha256=changed"), FILES[1]]) != base
    assert engine_digest([("pkg/c.py", "sha256=aa"), FILES[1]]) != base


def test_unhashed_file_fails() -> None:
    with pytest.raises(UnhashedFile):
        engine_digest([*FILES, ("pkg/c.py", None)])


def test_installed_digest_is_a_stable_sha256() -> None:
    first = installed_digest()
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert installed_digest() == first
