"""Standalone land test scratch fixture."""
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def workdir(tmp_path: Path) -> Iterator[Path]:
    yield tmp_path
