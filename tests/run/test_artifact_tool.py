"""Every worker call carries the artifact_add server, bound by its argv to the repo, bead, run, stage and the call's number."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import engine_case as te

BOUND = ("--repo", "--bead", "--run", "--stage", "--attempt", "--cwd")


def opts(argv):
    return {a: argv[i + 1] for i, a in enumerate(argv) if a in BOUND}


class ArtifactTool(te.EngineTest):
    def test_every_worker_call_gets_the_server_bound_to_its_own_run_stage_and_call_number(self):
        rc, script = self.run_engine({"plan": [te.PLAN], "write": [te.WRITE], "review": [te.review()]})
        assert rc == 0
        assert len(script.requests) == len(script.nodes) >= 3
        seen = []
        for req, cwd in zip(script.requests, script.cwds, strict=True):
            (tool,) = req.tools
            bound = opts(tool.command)
            assert "artifact-server" in tool.command
            assert (bound["--bead"], bound["--run"], bound["--cwd"]) == (tool.bead, tool.run, cwd)
            assert (bound["--stage"], int(bound["--attempt"])) == (tool.stage, tool.attempt)
            seen.append(tool.attempt)
        assert seen == sorted(set(seen))  # each delegate call has its own folder in the store
        assert len({opts(r.tools[0].command)["--run"] for r in script.requests}) == 1

    def test_the_server_takes_no_binding_from_the_model(self):
        from taskloop.app.artifacts import server  # noqa: PLC0415

        schema = server.TOOL["inputSchema"]
        assert isinstance(schema, dict) and schema["additionalProperties"] is False
        assert set(server.FIELDS) == {"path", "caption", "role", "name"}
