"""The recording land stage keeps the production stage's public contract."""
import inspect

import pytest
from support.fakegit import FakeGit
from support.narrow_land import table_kit

from taskloop.app.run.parts_land import LandStage
from tlland.testing import FakeLandStage
from tlpipeline.api import run_roles, standalone_roles


def assert_conforms(real: object, candidate: object) -> None:
    """Check the inherited LandStage members and bound callable signatures."""
    assert run_roles.Lander in LandStage.__mro__
    assert standalone_roles.Landing in LandStage.__mro__
    members = run_roles.Lander.__protocol_attrs__ | standalone_roles.Landing.__protocol_attrs__
    for name in sorted(members):
        assert hasattr(real, name), f"real stage missing {name}"
        assert hasattr(candidate, name), f"candidate stage missing {name}"
        actual, fake = getattr(real, name), getattr(candidate, name)
        if callable(actual):
            assert callable(fake), f"candidate {name} is not callable"
            expected = [(p.name, p.kind) for p in inspect.signature(actual).parameters.values()]
            assert [(p.name, p.kind) for p in inspect.signature(fake).parameters.values()] == expected, name


class MissingFinish:
    """A stage-shaped stub with the required finish operation absent."""

    def __init__(self) -> None:
        self.out = self.gate = FakeLandStage()


@pytest.mark.parametrize("missing_finish", [False, True], ids=["fake", "missing-finish"])
def test_land_stage_conformance(missing_finish: bool):
    real = table_kit(FakeGit()).lander
    if missing_finish:
        with pytest.raises(AssertionError, match="candidate stage missing finish"):
            assert_conforms(real, MissingFinish())
    else:
        assert_conforms(real, FakeLandStage())
