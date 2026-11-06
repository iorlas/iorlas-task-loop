"""engine.second_writer_family on a run: the chosen light bead's write carries --only-family <second> alone, a stop there parks the bead
with words naming the warm family, and the reviewer is still the other family (tl-7i9k.17)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import engine_case as te

COVERED = dict(te.PLAN, cases=[{"criterion": "the file f.txt exists", "check": te.adhoc(te.HAS_F), "class": "test"}, *te.PLAN["cases"]])
CHOSEN, OTHER = "t-24", "t-1"  # sha1(id) % 10: 0 and 3


def families(argv):
    return [argv[i + 1] for i, x in enumerate(argv) if x == "--only-family"]


class WarmFamily(te.EngineTest):
    def write_argv(self, bead, **cfg):
        done = te.stop("no_lane", say="claude is out")
        done["stop"]["reason"] = "only_family_unready"
        rc, script = self.run_engine({"plan": [te.PLAN], "write": [done]}, bead=bead, writer_family=["openai"], **cfg)
        return rc, script.argvs[script.nodes.index("write")]

    def test_the_chosen_light_bead_is_written_by_the_second_family_alone(self):
        _, argv = self.write_argv(CHOSEN, second_writer_family="claude")
        assert families(argv) == ["claude"]

    def test_any_other_bead_and_an_unset_key_keep_the_usual_pin(self):
        assert families(self.write_argv(OTHER, second_writer_family="claude")[1]) == ["openai"]
        assert families(self.write_argv(CHOSEN)[1]) == ["openai"]

    def test_a_stop_of_the_warm_family_parks_the_bead_in_words_naming_it(self):
        rc, _ = self.write_argv(CHOSEN, second_writer_family="claude")
        assert rc == 2
        said = self.said()
        assert "second writer family (claude)" in said
        assert "no other family is used" in said

    def test_the_reviewer_is_authored_by_the_second_family(self):
        _, script = self.run_engine(
            {"plan": [COVERED], "write": [te.WRITE], "review": [te.CLEAN]},
            bead=CHOSEN, writer_family=["openai"], second_writer_family="claude", review="off", j_extra={"write": [{"family": "claude"}]},
        )
        review = script.argvs[script.nodes.index("review")]
        assert review[review.index("--authored-by") + 1] == "claude"
