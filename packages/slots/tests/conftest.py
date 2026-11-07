"""Install Case cleanup helpers when running the slots package on its own."""
from collections.abc import Iterator

import pytest
from tltestkit.case import install_case_helpers


@pytest.fixture(autouse=True)
def slot_case_helpers(request: pytest.FixtureRequest) -> Iterator[None]:
    with install_case_helpers(request):
        yield
