"""Pinned writers keep engine-only recipes in their brief even when delegate cannot enforce the guard."""

import json
import sys
from pathlib import Path
from unittest import mock

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import engine_case as te

from taskloop.app.workers.worker_call import WorkerCall
from tlkernel.delegate import REASON_ENGINE_ONLY_UNENFORCED
from tltestkit.logs import records


class Request(Case):
    def test_advisory_requires_a_pinned_write_and_nonempty_recipes(self):
        for node, role, pinned, recipes, expected in (
            ("write", "worker", ["openai"], ["check"], True),
            ("write", "worker", [], ["check"], False),
            ("write", "worker", ["openai"], [], False),
            ("write", "worker", [], [], False),
            ("review", "reviewer", ["openai"], ["check"], False),
            ("plan", "planner", ["openai"], ["check"], False),
        ):
            with self.subTest(node=node, pinned=pinned, recipes=recipes):
                host = mock.Mock(session="s", bead="t-1")
                host.git.diff_entries.return_value = []
                host.plan_data = None
                host.cfg.writer_exec = False
                host.cfg.reviewer_other_family = True
                host.budget.labels = ["writer-family:" + f for f in pinned]
                host.checker.split.return_value.engine_recipes.return_value = recipes
                call = mock.Mock(node=node, role=role, cwd="/w", title="T", thread="writer", writer=None)
                with mock.patch("taskloop.app.workers.worker_request.planref.stage_commands", return_value=[]):
                    req = WorkerCall(host, mock.Mock()).request(call, "live", 60, 30)
                assert req.engine_only_advisory == expected
                assert req.engine_only == (recipes if node == "write" else [])
                assert req.prefer == (pinned[0] if pinned and role == "worker" else "")


class Advisory(te.EngineTest):
    def stopped_write(self, reason="no_lane", pinned=True, recipes=True, resumed=False):
        stopped = te.stop("no_lane", say="CODEX cannot enforce just check", fix="choose an enforcing harness")
        stopped["stop"]["reason"] = reason
        stopped["text"] = "full stop text " + "x" * 500
        stopped["trace"] = ["lane CODEX", "recipes: check"]
        steps = {"plan": [te.PLAN], "write": [te.WRITE, stopped] if resumed else [stopped]}
        if resumed:
            steps["review"] = [te.review(unmet=["more"])]
        with self.store.stub(show=dict(te.BEAD, labels=["writer-family:openai"] if pinned else [])):
            rc, script = self.run_engine(steps, gate="just check" if recipes else "")
        assert rc == 2
        assert self.blocked == []
        return script, stopped

    def test_pinned_write_sends_advisory_and_one_sentence_naming_the_recipes(self):
        script, _ = self.stopped_write()
        for node, argv, prompt in zip(script.nodes, script.argvs, script.prompts, strict=True):
            assert ("--engine-only-advisory" in argv) == (node == "write")
            assert prompt.count("the writer's harness may not deny them") == int(node == "write")
            if node == "write":
                assert "Do not run the engine-only recipes (just check)" in prompt

    def test_resumed_write_also_gets_the_advisory_sentence(self):
        script, _ = self.stopped_write(resumed=True)
        writes = [(argv, prompt) for node, argv, prompt in zip(script.nodes, script.argvs, script.prompts, strict=True)
                  if node == "write"]
        assert len(writes) == 2
        request = [r for r in script.requests if r.role == "worker"][1]
        assert request.thread == "writer"
        assert request.delta_file
        assert request.resume is None
        for argv, prompt in writes:
            assert "--engine-only-advisory" in argv
            assert prompt.count("the writer's harness may not deny them") == 1

    def test_unpinned_write_has_no_advisory_sentence_or_flag(self):
        script, _ = self.stopped_write(pinned=False)
        assert any("--engine-only" in a for a in script.argvs)
        for argv, prompt in zip(script.argvs, script.prompts, strict=True):
            assert "--engine-only-advisory" not in argv
            assert "the writer's harness may not deny them" not in prompt

    def test_pin_without_engine_recipes_has_no_advisory_sentence_or_flag(self):
        script, _ = self.stopped_write(recipes=False)
        for argv, prompt in zip(script.argvs, script.prompts, strict=True):
            assert "--engine-only-advisory" not in argv
            assert "the writer's harness may not deny them" not in prompt

    def test_unenforced_stop_pauses_with_its_words_and_fix(self):
        self.stopped_write(reason=REASON_ENGINE_ONLY_UNENFORCED)
        said = self.said()
        for text in ("paused: the writer's harness cannot deny the engine-only recipes:",
                     "CODEX cannot enforce just check", "choose an enforcing harness", REASON_ENGINE_ONLY_UNENFORCED):
            assert text in said

    def assert_stop_log(self, reason):
        script, stopped = self.stopped_write(reason=reason)
        rows = [r for r in records(self.eng, "note") if r["text"].startswith("write delegate stop: ")]
        assert len(rows) == 1
        detail = json.loads(rows[0]["text"].removeprefix("write delegate stop: "))
        assert detail["argv"] == script.argvs[script.nodes.index("write")]
        assert detail["argv"][detail["argv"].index("--brief") + 1]
        assert detail["stop"]["trace"] == stopped["trace"]
        assert detail["text"] == stopped["text"]
        assert stopped["text"] in json.loads(detail["trace"])["text"]

    def test_no_lane_stop_logs_one_typed_note_with_actual_argv_and_full_trace(self):
        self.assert_stop_log("no_lane")

    def test_only_family_unready_stop_logs_one_typed_note(self):
        self.assert_stop_log("only_family_unready")

    def test_engine_only_unenforced_stop_logs_one_typed_note(self):
        self.assert_stop_log(REASON_ENGINE_ONLY_UNENFORCED)


for _name in dir(te.EngineTest):
    if _name.startswith("test_") and _name not in Advisory.__dict__:
        setattr(Advisory, _name, None)
