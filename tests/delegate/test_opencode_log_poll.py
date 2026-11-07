"""The supervisor's log watcher: a limit phrase in a log line quoting the worker's own command must not mark the lane out."""

from pathlib import Path

import hermetic  # noqa: F401  (a home of its own for every test)
from any_agent import vendors
from any_agent.harnesses.opencode import OpenCodeHarness
from any_agent.supervisor import LogWatcher
from support.tmpdir import TemporaryDirectory

ECHO = [
    'INFO  2026-10-26T21:32:01 +3ms service=permission evaluated permission=bash pattern="cat <<EOF\\ntry again later\\nEOF" action=allow',
    'INFO  2026-10-26T21:32:02 +1ms service=permission evaluated permission=bash pattern="echo rate limit hit" action=allow',
]
REAL = "ERROR 2026-10-26T21:40:00 +9ms service=llm error=Rate limit reached for requests, try again later"


class LogWatch:
    def run_poll(self, lines):
        with TemporaryDirectory() as d:
            (Path(d) / "a.log").write_text("old\n")
            w = LogWatcher(Path(d), vendors.words().limit.search, OpenCodeHarness().echoes_input)
            with open(Path(d) / "a.log", "a") as f:
                f.write("\n".join(lines) + "\n")
            return w.poll()

    def test_echoed_tool_input_is_ignored(self):
        assert self.run_poll(ECHO) is None

    def test_real_limit_line_still_marks_out(self):
        stop = self.run_poll([*ECHO, REAL])
        assert stop is not None
        assert stop.why == "limit"
        assert "Rate limit reached" in stop.msg

    def test_lines_from_before_the_launch_are_not_seen(self):
        with TemporaryDirectory() as d:
            (Path(d) / "a.log").write_text(REAL + "\n")
            assert LogWatcher(Path(d), vendors.words().limit.search, OpenCodeHarness().echoes_input).poll() is None
