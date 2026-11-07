"""PROMPTCAP: every delegate call checks its input against its role's cap before it spawns. Over the cap, the run ends with a
Task fault (ASK_TICKET: the bead's brief is too big) and the call is never made; at the cap, it goes through."""

import re
import sys
from pathlib import Path
from unittest import mock

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import engine_case as te
from support.spawn import port_git, real_spawner
from support.who import who

from taskloop.app.run import engine
from taskloop.app.write import prompts as write
from taskloop.app.write import review_prompt as review
from taskloop.domain.lanes.roles import ROLES
from tlkernel import lanecaps as caps
from tlkernel.env import snapshot
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind, Task, fault_of
from tlslots import config as wslots_config
from tltestkit import fake_route
from tlwork.prompts import common


class Table(Case):
    def test_every_role_the_engine_calls_has_a_cap(self):
        assert set(ROLES.values()) <= set(caps.CAPS)

    def test_at_the_cap_passes_and_one_byte_over_is_refused(self):
        for role, cap in caps.CAPS.items():
            with self.subTest(role):
                assert caps.check(role, "x" * cap) is None
                over = caps.check(role, "x" * (cap + 1))
                assert over == caps.Over(role, cap + 1, cap)

    def test_the_size_is_bytes_not_characters(self):
        assert caps.check("worker", "é" * (caps.CAPS["worker"] // 2)) is None
        assert caps.check("worker", "é" * (caps.CAPS["worker"] // 2 + 1)) is not None

    def test_an_over_cap_brief_is_a_task_fault(self):
        assert isinstance(fault_of(Kind.ASK_TICKET), Task)

    def test_the_caps_clear_the_real_prompts(self):
        biggest = max(p.stat().st_size for p in (Path(__file__).resolve().parents[1] / "fixtures" / "prompts").glob("*.txt"))
        assert biggest * 2 < min(caps.CAPS.values())


class Feedback(Case):
    """READCAP: what the engine sends back to a worker (review findings) is cut to FEEDBACK_MAX with a pointer."""

    def test_a_fitting_text_is_unchanged(self):
        assert caps.cut("abc\n", 10) == "abc\n"

    def test_a_long_text_is_cut_at_a_line_and_says_what_was_left(self):
        text = "".join(f"- finding {i}\n" for i in range(1000))
        out = caps.cut(text, 200)
        assert len(out.encode("utf-8")) <= 200 + 120
        assert out.startswith("- finding 0\n")
        assert re.search(r"\(\d+ more lines left out", out)

    def test_the_prompts_tell_the_worker_to_read_by_range(self):
        for text in (write.WRITE_PROMPT, review.REVIEW_PROMPT):
            assert common.READ_RULE in text
        assert str(common.READ_LINES) in common.READ_RULE
        assert str(caps.RESULT_LINES) in common.READ_RULE


class Refusal(te.EngineTest):
    def go(self, role, script):
        c = wslots_config.load_cfg(str(self.wt), port_git())
        with te.delegate_stack(script), mock.patch.dict(caps.CAPS, {role: 1}):
            self.eng = engine.Engine(
                BeadId("t-1"), str(self.wt), c, store=self.store, env=snapshot(), spawner=real_spawner(), git=port_git(), who=who()
            )
            rc = self.eng.run()
        return rc

    def refused(self, role, answers):
        script = fake_route.Script(answers)
        rc = self.go(role, script)
        assert rc != 0
        assert role not in [r for r, _, _ in script.calls]  # nothing spawned for the refused role
        assert self.eng.kind == Kind.ASK_TICKET
        assert isinstance(fault_of(self.eng.kind), Task)
        assert f"over the 0 KB cap of the {role} role" in self.eng.why
        return script

    def test_an_over_cap_planner_brief_spawns_nothing(self):
        script = self.refused("planner", {"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})
        assert script.calls == []

    def test_an_over_cap_writer_brief_spawns_no_writer_and_no_reviewer(self):
        script = self.refused("worker", {"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})
        assert [r for r, _, _ in script.calls] == ["planner"]

    def test_an_over_cap_reviewer_brief_spawns_no_reviewer(self):
        self.refused("reviewer", {"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})


for _name in dir(te.EngineTest):  # the engine fixture only
    if _name.startswith("test_") and _name not in Refusal.__dict__:
        setattr(Refusal, _name, None)
