"""`instructions_ref`: a worker reads the repo's instruction files as committed at a commit, not the work tree's (tl-7i9k.58)."""
import pytest
from delegate.app import decide, launch
from delegate.contracts import wire
from delegate.contracts.json_types import Json

CONTRACT: dict[str, Json] = {"contract": wire.CONTRACT, "capabilities": list(wire.CAPABILITIES)}
OLD: dict[str, Json] = {"contract": wire.CONTRACT, "capabilities": ["writer_exec_allow"]}


def request(**kw):
    return wire.RunRequest(role="reviewer", brief_file="b.md", cwd="/w", **kw)


def test_the_ref_travels_as_a_flag_only_with_the_capability():
    argv = request(instructions_ref="abc123").to_argv("route.py", contract=CONTRACT)
    assert argv[argv.index("--instructions-ref") + 1] == "abc123"
    assert "--instructions-ref" not in request().to_argv("route.py", contract=CONTRACT)


@pytest.mark.parametrize("contract", [None, OLD])
def test_an_older_delegate_refuses_the_ref_at_admission(contract):
    with pytest.raises(ValueError, match="instructions_ref"):
        request(instructions_ref="abc123").to_argv("route.py", contract=contract)


def test_codex_loads_no_project_doc_when_a_ref_is_given():
    assert decide.instruction_isolation("abc123") == ["-c", "project_doc_max_bytes=0"]
    assert decide.instruction_isolation("") == []


def test_opencode_cannot_honor_a_ref_and_is_refused():
    assert "opencode" in launch.ref_problem("opencode", "abc123")
    assert launch.ref_problem("opencode", "") == ""
    assert launch.ref_problem("codex", "abc123") == launch.ref_problem("claude_p", "abc123") == ""
