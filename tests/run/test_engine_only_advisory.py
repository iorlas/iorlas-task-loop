"""Pinned writers keep engine-only recipes in their brief even when delegate cannot enforce the guard."""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import engine_case as te
from support.logs import records

from taskloop.app.run.worker_call import WorkerCall
from taskloop.contracts.delegate import REASON_ENGINE_ONLY_UNENFORCED


class Request(unittest.TestCase):
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
                host.cfg.writer_family = pinned
                host.budget.labels = []
                host.checker.split.return_value.engine_recipes.return_value = recipes
                call = mock.Mock(node=node, role=role, cwd="/w", title="T", resume=None, writer=None)
                with mock.patch("taskloop.app.run.worker_request.planref.stage_commands", return_value=[]):
                    req = WorkerCall(host, mock.Mock()).request(call, "live", 60, 30)
                self.assertEqual(req.engine_only_advisory, expected)
                self.assertEqual(req.engine_only, recipes if node == "write" else [])
                self.assertEqual(req.only_family, pinned if role == "worker" else [])


class Advisory(te.EngineTest):
    def stopped_write(self, reason="no_lane", pinned=True, recipes=True, resumed=False):
        stopped = te.stop("no_lane", say="CODEX cannot enforce just check", fix="choose an enforcing harness")
        stopped["stop"]["reason"] = reason
        stopped["text"] = "full stop text " + "x" * 500
        stopped["trace"] = ["lane CODEX", "recipes: check"]
        steps = {"plan": [te.PLAN], "write": [te.WRITE, stopped] if resumed else [stopped]}
        if resumed:
            steps["review"] = [te.review(unmet=["more"])]
        rc, script = self.run_engine(
            steps, writer_family=["openai"] if pinned else [],
            gate="just check" if recipes else "",
        )
        self.assertEqual(rc, 2)
        self.assertEqual(self.blocked, [])
        return script, stopped

    def test_pinned_write_sends_advisory_and_one_sentence_naming_the_recipes(self):
        script, _ = self.stopped_write()
        for node, argv, prompt in zip(script.nodes, script.argvs, script.prompts, strict=True):
            self.assertEqual("--engine-only-advisory" in argv, node == "write")
            self.assertEqual(prompt.count("the writer's harness may not deny them"), int(node == "write"))
            if node == "write":
                self.assertIn("Do not run the engine-only recipes (just check)", prompt)

    def test_resumed_write_also_gets_the_advisory_sentence(self):
        script, _ = self.stopped_write(resumed=True)
        writes = [(argv, prompt) for node, argv, prompt in zip(script.nodes, script.argvs, script.prompts, strict=True)
                  if node == "write"]
        self.assertEqual(len(writes), 2)
        self.assertIn("--resume", writes[1][0])
        for argv, prompt in writes:
            self.assertIn("--engine-only-advisory", argv)
            self.assertEqual(prompt.count("the writer's harness may not deny them"), 1)

    def test_unpinned_write_has_no_advisory_sentence_or_flag(self):
        script, _ = self.stopped_write(pinned=False)
        self.assertTrue(any("--engine-only" in a for a in script.argvs))
        for argv, prompt in zip(script.argvs, script.prompts, strict=True):
            self.assertNotIn("--engine-only-advisory", argv)
            self.assertNotIn("the writer's harness may not deny them", prompt)

    def test_pin_without_engine_recipes_has_no_advisory_sentence_or_flag(self):
        script, _ = self.stopped_write(recipes=False)
        for argv, prompt in zip(script.argvs, script.prompts, strict=True):
            self.assertNotIn("--engine-only-advisory", argv)
            self.assertNotIn("the writer's harness may not deny them", prompt)

    def test_unenforced_stop_pauses_with_its_words_and_fix(self):
        self.stopped_write(reason=REASON_ENGINE_ONLY_UNENFORCED)
        said = self.said()
        for text in ("paused: the writer's harness cannot deny the engine-only recipes:",
                     "CODEX cannot enforce just check", "choose an enforcing harness", REASON_ENGINE_ONLY_UNENFORCED):
            self.assertIn(text, said)

    def assert_stop_log(self, reason):
        script, stopped = self.stopped_write(reason=reason)
        rows = [r for r in records(self.eng, "note") if r["text"].startswith("write delegate stop: ")]
        self.assertEqual(len(rows), 1)
        detail = json.loads(rows[0]["text"].removeprefix("write delegate stop: "))
        self.assertEqual(detail["argv"], script.argvs[script.nodes.index("write")])
        self.assertTrue(detail["argv"][detail["argv"].index("--brief") + 1])
        self.assertEqual(detail["stop"]["trace"], stopped["trace"])
        self.assertEqual(detail["text"], stopped["text"])
        self.assertIn(stopped["text"], json.loads(detail["trace"])["text"])

    def test_no_lane_stop_logs_one_typed_note_with_actual_argv_and_full_trace(self):
        self.assert_stop_log("no_lane")

    def test_only_family_unready_stop_logs_one_typed_note(self):
        self.assert_stop_log("only_family_unready")

    def test_engine_only_unenforced_stop_logs_one_typed_note(self):
        self.assert_stop_log(REASON_ENGINE_ONLY_UNENFORCED)


for _name in dir(te.EngineTest):
    if _name.startswith("test_") and _name not in Advisory.__dict__:
        setattr(Advisory, _name, None)


if __name__ == "__main__":
    unittest.main()
