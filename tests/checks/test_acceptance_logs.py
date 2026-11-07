"""Acceptance checks can consume every saved check log in this run."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import procsim
from support.check_host import CheckHostCase

from tlkernel.checks import Check
from tlkernel.ids import CheckId


class AcceptanceLogs(CheckHostCase):
    def test_acceptance_log_is_published_and_survives_separate_check_blocks(self):
        seen = []

        def reader(cwd, env):
            seen.append(dict(env))
            return 0, Path(env["TL_CHECK_LOG_FIRST"]).read_text()

        read = procsim.fake("read-first-log", reader)
        e = self.checks_engine()
        first = Check(id=CheckId("first"), cmd="true", group="acceptance", cache=False)
        second = Check(id=CheckId("second"), cmd=read, group="acceptance", cache=False)
        e.checker.run_items([first, second])
        e.checker.run_items([second])
        assert len(seen) == 2
        for env in seen:
            assert Path(env["TL_CHECK_LOG_FIRST"]).is_file()
            assert env["TL_CHECK_RC_FIRST"] == "0"
            assert "TL_CHECK_LOG_NEVER" not in env

    def test_missing_log_keyerror_explains_which_checks_have_logs(self):
        for prefix in ("TL_CHECK_LOG_", "TL_CHECK_RC_"):
            with self.subTest(prefix=prefix):
                output = f"Traceback (most recent call last):\nKeyError: '{prefix}NEVER'"
                fail = procsim.fake("missing-" + prefix, lambda cwd, env, text=output: (1, text))
                e = self.checks_engine()
                run = e.checker.run_items([
                    Check(id=CheckId("first"), cmd="true", group="tests", cache=False),
                    Check(id=CheckId("reader"), cmd=fail, group="acceptance", cache=False),
                ])
                tail = next(r.tail for r in run if r.id == "reader")
                assert output in tail
                assert "the check log variable is missing: that check did not run in this attempt (ids with a log:" in tail
                assert "first" in tail.splitlines()[-1]
