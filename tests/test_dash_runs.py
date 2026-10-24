"""/api/runs reads each file once (tl-bxk.8.26: it took seconds cold because every subagent file re-read its whole session)."""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop" / "dash"))
import server  # noqa: E402


def agent(d, n, desc):
    p = d / "subagents" / ("agent-%d.jsonl" % n)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"timestamp": "2026-10-24T10:00:00Z"}) + "\n")
    p.with_suffix(".meta.json").write_text(json.dumps({"description": desc, "model": "sonnet", "agentType": "general"}))
    return p


class Runs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.projects = Path(self.tmp.name) / "projects"
        self.sess = self.projects / "-proj" / "sess1"
        self.paths = [agent(self.sess, i, "agent %d" % i) for i in range(4)]
        server._cache.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def test_each_subagent_file_is_read_once_not_once_per_agent_of_its_session(self):
        with mock.patch.object(server, "PROJECTS", self.projects), mock.patch.object(server, "codex_jobs", lambda s: []), \
                mock.patch.object(server, "codex_rollouts", lambda s: []), mock.patch.object(server, "contract_runs", lambda s: []), \
                mock.patch.object(server, "first_json", wraps=server.first_json) as fj:
            runs = server.all_runs(24 * 365 * 10)
        self.assertEqual(sorted(r["title"] for r in runs), ["agent %d" % i for i in range(4)])
        self.assertEqual(fj.call_count, 4)

    def test_a_subagent_outside_the_window_is_none(self):
        self.assertIsNone(server.subagent_run(str(self.paths[0]), t0=time.time(), t1=time.time() + 5))
        self.assertEqual(server.subagent_run(str(self.paths[0]))["title"], "agent 0")

    def test_transcript_index_names_the_newest_of_a_session_across_projects(self):
        old, new = self.projects / "-a" / "s9.jsonl", self.projects / "-b" / "s9.jsonl"
        for p in (old, new):
            p.parent.mkdir(parents=True)
            p.write_text("{}\n")
        os.utime(str(old), (1, 1))
        with mock.patch.object(server, "PROJECTS", self.projects):
            self.assertEqual(server.transcript_index()["s9"], str(new))


if __name__ == "__main__":
    unittest.main()
