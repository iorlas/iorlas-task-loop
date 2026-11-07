"""The public API's thread prompts reach the fake worker CLI."""

import os
from dataclasses import replace
from pathlib import Path

from run_support import RunBase

from delegate import api
from delegate.app import env
from tltestkit.procsim import real_proc

LIMIT_S = 60  # each test runs a fake CLI and git


class TestThreadWorkers(RunBase):
    @real_proc("delegate: a worker, git or CLI process")
    def test_full_then_delta_reach_the_worker(self):
        whole, delta = self.base / "whole.md", self.base / "delta.md"
        whole.write_text("whole prompt")
        delta.write_text("delta prompt")
        os.environ["FAKE_MODE"] = "ok"
        request = api.RunRequest(
            role="worker",
            brief_file=str(whole),
            cwd=self.repo,
            task="bead",
            thread="writer",
            only_family=["openai"],
        )
        first = api.run(request)
        assert first.stop is None, first.say
        assert first.text == "done: whole prompt"
        assert env.load_state().threads["bead/writer"].ref == first.ref
        second = api.run(replace(request, delta_file=str(delta)))
        assert second.stop is None, second.say
        assert second.text == "done: delta prompt"
        assert "resume" in Path(os.environ["FAKE_ARGS"]).read_text()
        assert env.load_state().threads["bead/writer"].ref == second.ref
