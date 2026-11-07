"""Install Case cleanup helpers when running the slots package on its own."""
from collections.abc import Iterator
from pathlib import Path

import pytest
from tlkernel import factorydb
from tlkernel.factoryparts import SLOTS, WORKTREE
from tltestkit.case import install_case_helpers

factorydb.declare_parts((SLOTS, WORKTREE))


@pytest.fixture(autouse=True)
def slot_case_helpers(request: pytest.FixtureRequest) -> Iterator[None]:
    with install_case_helpers(request):
        yield


@pytest.fixture
def workdir(tmp_path: Path) -> Iterator[Path]:
    yield tmp_path
