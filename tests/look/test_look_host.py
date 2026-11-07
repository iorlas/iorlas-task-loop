"""The Engine satisfies LookHost: every member the look stage names is on the engine a run builds."""
from support.builders import make_engine
from support.engine_case import EngineTest
from support.host_conformance import missing
from support.look_host import FakeLook

from tlwork.look.host import LookHost, LookPorts


class LookHostConformance(EngineTest):
    def test_the_engine_has_every_member_the_look_stage_reads(self):
        eng = make_engine(self.wt, store=self.store)
        assert (missing(eng, LookHost), missing(eng, LookPorts)) == ([], [])

    def test_the_check_names_a_member_the_host_lacks(self):
        eng = make_engine(self.wt, store=self.store)
        del eng.steps
        assert missing(eng, LookPorts) == ["steps"]


class RenderHandOff(EngineTest):
    """Write tells the look stage its pictures are old through `pictures.mark_stale()`, and the repo key comes from the one port."""

    def test_a_write_marks_the_pictures_stale_through_the_pictures_not_a_field_write(self):
        eng = make_engine(self.wt, store=self.store)
        assert not eng.pictures.stale
        eng.pictures.mark_stale()
        assert (eng.pictures.stale, eng.render_stale) == (True, True)  # the checkpointed flag is the same one

    def test_the_look_stage_takes_the_repo_key_from_the_port_and_the_engine_memo_agrees(self):
        eng = make_engine(self.wt, store=self.store)
        key = eng.ports.repo.key()
        eng.pictures.show_pictures()
        assert eng.artifact_repo == key


def test_the_fake_look_has_every_member_the_stage_reads(workdir):
    look = FakeLook(workdir)
    assert (missing(look.ports, LookPorts), missing(look.hand, LookHost)) == ([], [])

def test_the_fake_look_sink_writes_its_hand_off_list(workdir):
    look = FakeLook(workdir)
    lo = {"title": "later"}
    assert look.ports.leftover_sink.add_titled(lo)
    assert look.hand.leftovers == [lo]
