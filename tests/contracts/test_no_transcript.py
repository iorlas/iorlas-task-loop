"""Task-loop records and trace output carry session references only."""
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from taskloop.app.track import verbs
from tlkernel import delegate, log, trace, wire
from tlkernel.env import Env
from tlkernel.ids import BeadId
from tlkernel.paths import ConfigDir
from tltestkit.tmpdir import TemporaryDirectory


def test_records_and_trace_have_no_transcript(monkeypatch):
    for record in (delegate.DelegateResult, log.CallEnd, trace.AiCall):
        assert not any("transcript" in name for name in wire.names(record))
    with TemporaryDirectory() as directory:
        root = Path(directory)
        session = trace.AiCall(node="write", role="worker", family="test", status="done", ref="session-ref", t=1)
        ConfigDir(root).traces().write_text(json.dumps({"run": "r", "sessions": [session.to_dict()]}) + "\n")
        env = Env({"XDG_CONFIG_HOME": str(root.parent)})
        monkeypatch.setattr(verbs, "config_dir", lambda env: root)
        out = io.StringIO()
        with redirect_stdout(out):
            assert verbs.trace(BeadId(""), 0, False, env) == 0
        output = out.getvalue()
        assert "transcript" not in output
        assert all(value in output for value in ("write", "worker", "test", "done", "session-ref"))
    for record, stale in ((log.CallEnd, {"v": 3}), (trace.RunTrace, {"v": 3})):
        with pytest.raises(wire.StaleRecord):
            wire.load(record, stale)
