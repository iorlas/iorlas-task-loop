"""A check stopped at its wall limit is not the writer's to fix. The engine run that parks on it is in test_stages (Fdyo)."""

from tlkernel.checks import CheckResult
from tltestkit.case import Case
from tltestkit.checks import res

from tlgate import evidence


def result(**kw) -> CheckResult:
    return res(**kw)


class Decision(Case):
    def test_table(self):
        slow = result(id="u", exit=124, wall_hit=True, wall_min=2.0)
        rows = [("no failed check", [], None), ("red, not timed out", [result()], None),
                ("exit 124 of the command's own is not the engine's limit", [result(exit=124)], None),
                ("the wall hit", [result(), slow], slow)]
        for name, failed, want in rows:
            with self.subTest(name):
                assert evidence.timed_out(failed) is want

    def test_the_reason_names_the_check_and_the_limit(self):
        assert evidence.timeout_why(result(id="unity", wall_min=2.0)) == "check unity timed out after 2 min (wall_min=2)"
