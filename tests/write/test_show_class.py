"""tl-jvpm.25: a `show` case names artifacts (name and role) that the writer registers; the engine checks them in the store for the
write's attempt. A miss goes back to the writer once with the reason and never parks; the planner is sent back once for a visual path
touched with no look-objective, taste or show case."""
import sys
from pathlib import Path
from typing import ClassVar

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import engine_case as T
from support.plans import CLEAN, PLAN, WRITE

from taskloop.app.artifacts import store
from taskloop.app.write import show_check

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
CASES = [{"criterion": "the board is shown", "check": None, "class": "show",
          "shows": [{"name": "board.png", "role": "after"}]}]


class Missing(Case):
    def test_a_registered_name_with_its_role_is_met_and_any_other_is_a_miss(self):
        with TemporaryDirectory() as d:
            root, src = Path(d) / "store", Path(d) / "board.png"
            src.write_bytes(PNG)
            slot = show_check.slot_of("repo", "t-1", "run1", 1)
            assert len(show_check.missing(CASES, root, slot)) == 1
            store.add(root, slot, src, name="board.png", caption="the board", role="before", now=1.0)
            assert "board.png (role after)" in show_check.missing(CASES, root, slot)[0]  # right name, wrong role
            store.add(root, slot, src, name="board.png", caption="the board", role="after", now=2.0)
            assert show_check.missing(CASES, root, slot) == []
            assert show_check.missing(CASES, root, show_check.slot_of("repo", "t-1", "run1", 2)) != []  # another attempt

    def test_no_show_case_checks_nothing(self):
        assert show_check.missing([{"criterion": "c", "check": None, "class": "taste"}], Path("/nonexistent"),
                                  show_check.slot_of("r", "b", "x", 1)) == []


class ShowRetry(T.LandReviewBase):
    def test_a_missing_artifact_goes_back_to_the_writer_once_and_never_parks(self):
        plan = dict(PLAN, cases=CASES)
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE, WRITE], "review": [CLEAN]})
        assert rc == 0, self.blocked
        writes = [p for n, p in zip(s.nodes, s.prompts, strict=False) if n == "write"]
        assert len(writes) == 2
        assert "board.png" in writes[1] and "not registered" in writes[1]
        assert "not registered" not in writes[0]


class VisualPathCheck(T.LandReviewBase):
    VISUAL: ClassVar = {"include": ["*.txt"], "exclude": []}

    def test_a_visual_path_with_no_visual_case_sends_the_plan_back_once(self):
        bare = dict(PLAN, cases=[])
        rc, s = self.run_engine({"plan": [bare, PLAN], "write": [WRITE], "review": [CLEAN]}, visual_paths=self.VISUAL)
        assert rc == 0, self.blocked
        assert s.nodes.count("plan") == 2
        assert "visual paths" in s.prompts[s.nodes.index("plan") + 1]

    def test_the_second_answer_stands_even_with_no_visual_case(self):
        bare = dict(PLAN, cases=[])
        rc, s = self.run_engine({"plan": [bare, bare], "write": [WRITE], "review": [CLEAN]}, visual_paths=self.VISUAL)
        assert rc == 0, self.blocked
        assert s.nodes.count("plan") == 2
