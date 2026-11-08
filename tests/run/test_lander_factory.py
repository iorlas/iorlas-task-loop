"""An Engine builds its injected landing capabilities once per host."""
from support.builders import make_engine
from support.engine_case import EngineTest

from taskloop.app.run.parts_land import LandStage
from tlland.testing import FakeLandStage


class Injection(EngineTest):
    def test_factory_is_cached_per_host(self):
        factory = FakeLandStage()
        first = make_engine(self.wt, lander_factory=factory)
        second = make_engine(self.wt, lander_factory=factory)
        stage: LandStage = factory
        assert first.lander is stage
        assert first.lander is stage
        assert second.lander is stage
        assert second.lander is stage
        assert factory.hosts == [first, second]
