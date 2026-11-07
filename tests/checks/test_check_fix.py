"""A check may name a fix command: it runs before the round and what it changed is what the checks see."""
import shlex
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import gitq, procsim
from support.check_host import CheckHostCase

# isort: split
from tlkernel.config import ConfigError, load


def format_a(cwd, env):
    (cwd / "a.txt").write_text("formatted\n")
    return 0, ""


FIX = shlex.split(procsim.default("format-a", format_a))  # a formatter: rewrites a.txt
SEES = procsim.default("sees-formatted", lambda cwd, env: (0 if (cwd / "a.txt").read_text() == "formatted\n" else 1, ""))  # green only then


class CheckFixTest(CheckHostCase):
    def run_round(self, **check):
        eng = self.checks_engine(checks=[{"id": "fmt", "cmd": SEES, "group": "static", **check}])
        return eng, eng.run_checks({"checks": [], "files": []}, "s")

    def test_a_check_is_checked_on_the_tree_its_fix_made(self):
        eng, res = self.run_round(fix=FIX)
        assert res[0].exit == 0
        assert (self.wt / "a.txt").read_text() == "formatted\n"
        assert "a.txt" in gitq.git("diff", "--cached", "--name-only", cwd=eng.wt)  # staged like the stage's own changes

    def test_without_a_fix_the_check_sees_the_tree_as_it_is(self):
        _, res = self.run_round()
        assert res[0].exit != 0
        assert (self.wt / "a.txt").read_text() != "formatted\n"

    def test_a_failing_fix_is_the_checks_red_and_keeps_its_error(self):
        boom = shlex.split(procsim.fake("csharpier", procsim.exits(3, "csharpier exploded")))
        _, res = self.run_round(fix=boom)
        assert (res[0].status, res[0].exit) == ("failed", 3)
        assert "csharpier exploded" in res[0].tail
        assert "fix command" in res[0].tail

    def test_the_profile_takes_the_fix_as_an_argv_only(self):
        ok = load({"engine": {"checks": [{"id": "f", "argv": ["true"], "fix": ["fmt", "--write"]}]}})
        assert ok.engine.checks[0].fix == ["fmt", "--write"]
        with pytest.raises(ConfigError):
            load({"engine": {"checks": [{"id": "f", "argv": ["true"], "fix": [""]}]}})
