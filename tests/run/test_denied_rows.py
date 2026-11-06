"""A denied row of a trace carries the kind and the reason the refuser gave, not only the tool and its input."""

from taskloop.adapters.delegate_wire import denied_of
from taskloop.app.run.trace import ai_call


def test_a_denied_row_keeps_kind_and_reason_from_the_wire_to_the_trace():
    wire = [{"kind": "policy", "tool": "Bash", "path": None, "input": {"command": "curl x"}, "reason": "reviewer declined"}]
    (d,) = denied_of(wire)
    assert d.reason == "reviewer declined"
    row = {"node": "n", "family": "f", "ref": "r", "status": "ok", "role": "w", "t": 1.0,
           "denied": [{"kind": d.kind, "tool": d.tool, "input": d.input, "reason": d.reason}]}
    (t,) = ai_call(row).denied
    assert (t.kind, t.tool, t.reason) == ("policy", "Bash", "reviewer declined")


def test_a_wire_denial_without_a_reason_reads_as_none():
    (d,) = denied_of([{"kind": "secret", "tool": "Bash", "input": {}}])
    assert d.reason is None


def test_a_write_call_carries_the_profile_read_roots_to_the_argv():
    from taskloop.contracts.delegate import RunRequest

    req = RunRequest(role="write", brief_path="b", cwd="/w", schema_path="s", read_roots=["/a", "/b"])
    argv = req.to_argv("python3", "route.py")
    assert [argv[i + 1] for i, x in enumerate(argv) if x == "--read-root"] == ["/a", "/b"]
