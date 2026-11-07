"""Standalone work tests prohibit processes and own their temporary folders."""
import contextlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from tltestkit import procsim


@pytest.fixture
def workdir(tmp_path: Path) -> Iterator[Path]:
    yield tmp_path


@pytest.fixture(autouse=True)
def process_guard() -> Iterator[None]:
    world = procsim.Procs("work-package", guarded=True)
    with contextlib.ExitStack() as stack:
        world.install(stack)
        yield
    world.check()
