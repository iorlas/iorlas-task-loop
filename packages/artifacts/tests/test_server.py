"""The artifact_add stdio server: protocol replies, the binding it keeps, and errors that go back to the model."""
import io
import json
from pathlib import Path

from tlartifacts import server, store
from tlkernel.artifact import ArtifactSlot

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 64
SLOT = ArtifactSlot(repo="r-1", bead="r-9", run="r-9-1", stage="write", attempt=1)


def talk(tmp_path: Path, *msgs: dict) -> list[dict]:
    out = io.StringIO()
    lines = [json.dumps(m) for m in msgs] + ["not json", "[]"]
    server.serve(lines, out, tmp_path / "store", SLOT, tmp_path / "wt", lambda: 7.0)
    return [json.loads(x) for x in out.getvalue().splitlines()]


def tool_call(i: int, **args) -> dict:
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": "artifact_add", "arguments": args}}


def test_the_tool_is_listed_with_a_closed_schema_and_a_call_registers_the_file(tmp_path):
    (tmp_path / "wt").mkdir()
    (tmp_path / "wt" / "a.png").write_bytes(PNG)
    got = talk(tmp_path, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
               {"jsonrpc": "2.0", "method": "notifications/initialized"},
               {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
               tool_call(3, path="a.png", caption="home", role="after", name="home.png", bead="other", run="x"))
    assert got[0]["result"]["protocolVersion"] == "2025-03-26"
    tool = got[1]["result"]["tools"][0]
    assert tool["name"] == "artifact_add" and tool["inputSchema"]["additionalProperties"] is False
    assert "progress" in tool["description"] and "before" in tool["description"]
    assert got[2]["result"]["isError"] is False
    # the model cannot choose bead or run: the extra arguments are ignored and the argv binding decides
    meta = store.listing(store.folder(tmp_path / "store", SLOT))
    assert [(m.name, m.role, m.created) for m in meta] == [("home.png", "after", 7.0)]


def test_a_refusal_is_an_error_result_the_model_can_read_and_a_retry_works(tmp_path):
    (tmp_path / "wt").mkdir()
    (tmp_path / "wt" / "a.png").write_bytes(PNG)
    got = talk(tmp_path, tool_call(1, path="../a.png", caption="c", role="after", name="a.png"),
               tool_call(2, path="a.png", caption="c", role="after", name="../a.png"),
               tool_call(3, path="a.png", caption="c", role="after"),
               tool_call(4, path="a.png", caption="c", role="after", name="a.png"))
    flags = [r["result"]["isError"] for r in got]
    assert flags == [True, True, True, False]
    assert "outside the working folder" in got[0]["result"]["content"][0]["text"]
    assert "name is required" in got[2]["result"]["content"][0]["text"]


def test_an_unknown_tool_is_a_protocol_error(tmp_path):
    got = talk(tmp_path, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "other"}})
    assert got[0]["error"]["code"] == -32602
