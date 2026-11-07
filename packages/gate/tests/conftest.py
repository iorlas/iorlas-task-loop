"""Install the standalone process guard for package tests without the application fixtures."""
import contextlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from tltestkit import procsim


@pytest.fixture
def workdir(tmp_path: Path) -> Iterator[Path]:
    yield tmp_path


@pytest.fixture
def commands():
    world = procsim.Procs("gate-package", guarded=True)
    with contextlib.ExitStack() as stack:
        world.install(stack)
        yield procsim
    world.check()
