"""Released harness launch specs, local credentials and the shared strict answer path, without vendor execution."""

import json
from pathlib import Path
from uuid import UUID

import pytest
from any_agent import RunOutcome, Summary
from any_agent.access import CodexSandbox
from any_agent.testing import FakeRun
from doubles import FixedIds
from test_attempt import ENTRY, KEY, PLAN, WORKER, AttemptSurroundings, app, database
from test_attempt import surroundings as attempt_surroundings

from taskloop.agent_credentials import machine_credentials
from taskloop.agents.launch import AgentLaunch, CredentialReason, CredentialsUnavailable, LaunchedAgent, LaunchFailure
from taskloop.agents.settings import AgentSetting, ClaudePolicy, CodexPolicy, OpenCodePolicy, encode_policy
from taskloop.evidence_files import EvidenceFiles
from taskloop.harness_choice import HarnessKind
from taskloop.ids import NativeIds


def setting(harness: HarnessKind, tmp_path: Path) -> AgentSetting:
    policy = (CodexPolicy() if harness is HarnessKind.CODEX else
              ClaudePolicy(settings_file=tmp_path / "deleted.json", settings='{"env":{"OPAQUE":"value"}}')
              if harness is HarnessKind.CLAUDE else OpenCodePolicy())
    return AgentSetting(harness=harness, model="chosen", effort="medium", access=policy)


@pytest.mark.parametrize("harness", list(HarnessKind))
@pytest.mark.parametrize("prepared", [False, True])
def test_released_harnesses_receive_typed_choices_and_writable_steps(tmp_path: Path, harness: HarnessKind, prepared: bool) -> None:
    files = EvidenceFiles(tmp_path)
    schema, out = files.prepare(KEY, {"type": "object", "properties": {}})
    root = files.launch_root(KEY)
    asked: list[HarnessKind] = []
    ids = FixedIds()
    adapter = AgentLaunch(lambda kind: (asked.append(kind) or f"/bin/{kind}", {"HOME": str(tmp_path)}), ids=ids)
    result = adapter.build(setting(harness, tmp_path), tmp_path / "slot", prepared, root, schema, out, "Task input")
    assert isinstance(result, LaunchedAgent)
    try:
        argv = result.spec.argv
        assert asked == [harness] and "chosen" in argv
        assert ids.sessions == ["00000000-0000-4000-8000-000000000001"]
        prompt = result.spec.stdin or argv[-1]
        # Claude's prompt is passed on stdin as well; every harness gets the answer contract.
        assert "Return exactly one JSON object" in result.spec.stdin
        if harness is HarnessKind.CODEX:
            assert 'model_reasoning_effort="medium"' in argv
            assert (result.probe is not None) is prepared
        elif harness is HarnessKind.CLAUDE:
            assert result.probe is None and "medium" in argv
            assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
            assert argv[argv.index("--session-id") + 1] == ids.sessions[0]
            assert json.loads(argv[argv.index("--settings") + 1]) == {"env": {"OPAQUE": "value"}}
            assert "Write" in argv[argv.index("--tools") + 1] and "--json-schema" in argv and "--session-id" in argv
        else:
            assert result.probe is None and argv[argv.index("--variant") + 1] == "medium"
            config = json.loads(result.spec.env["OPENCODE_CONFIG_CONTENT"])
            assert "edit" not in config["permission"]  # both steps edit files
            assert Path(result.spec.env["SHELL"]).is_relative_to(root)
        assert prompt
    finally:
        result.harness.cleanup()


def test_codex_full_access_asks_for_no_sandbox_and_no_probe(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    schema, out = files.prepare(KEY, {"type": "object", "properties": {}})
    full = AgentSetting(model="chosen", access=CodexPolicy(sandbox=CodexSandbox.DANGER_FULL_ACCESS))
    adapter = AgentLaunch(lambda kind: (f"/bin/{kind}", {"HOME": str(tmp_path)}), ids=NativeIds())
    result = adapter.build(full, tmp_path / "slot", True, files.launch_root(KEY), schema, out, "Task input")
    assert isinstance(result, LaunchedAgent)
    try:
        argv = result.spec.argv
        assert result.probe is None and argv[argv.index("-s") + 1] == "danger-full-access"
        assert 'approval_policy="never"' in argv and not any("sandbox_workspace_write" in item for item in argv)
    finally:
        result.harness.cleanup()


@pytest.mark.parametrize("harness", [HarnessKind.CLAUDE, HarnessKind.OPENCODE])
def test_non_codex_credentials_only_find_the_selected_executable(harness: HarnessKind) -> None:
    looked: list[str] = []

    def which(cmd: str, mode: int = 1, path: str | None = None) -> str:
        looked.append(cmd)
        return f"/bin/{cmd}"

    def forbidden(_path: Path) -> bool:
        pytest.fail("non-Codex credentials must not inspect Codex login files")

    exe, env = machine_credentials(harness, {"PATH": "/bin", "HOME": "/home/p", "SECRET": "hidden"}, which, forbidden)
    assert exe == f"/bin/{harness}" and looked == [harness] and "SECRET" not in env


@pytest.mark.parametrize("reason", list(CredentialReason))
def test_every_typed_credential_failure_has_a_useful_explanation(tmp_path: Path, reason: CredentialReason) -> None:
    def unavailable(_harness: HarnessKind) -> tuple[str, dict[str, str]]:
        raise CredentialsUnavailable(reason, "The local login or executable is unavailable.")

    result = AgentLaunch(unavailable, ids=NativeIds()).build(AgentSetting(), tmp_path, False, tmp_path, "unused", "unused", "input")
    assert isinstance(result, LaunchFailure) and result.explanation and "credentials:" in result.reason


@pytest.mark.parametrize("harness", list(HarnessKind))
@pytest.mark.parametrize("answer,kind", [(json.dumps(PLAN), "valid"), ("{", "json_invalid"), ("{}", "schema_invalid")])
def test_all_harnesses_use_the_same_strict_step_decoder(
    tmp_path: Path, surroundings: AttemptSurroundings, harness: HarnessKind, answer: str, kind: str,
) -> None:
    con = database(surroundings)
    chosen = setting(harness, tmp_path)
    con.execute("UPDATE attempt SET harness=?,provider=?,model=?,effort=?,access_policy=?",
                (chosen.harness, chosen.provider, chosen.model, chosen.effort, encode_policy(chosen.access)))
    run = FakeRun(RunOutcome(rc=0, worker=WORKER, summary=Summary(text=answer, rc=0, stands=True)))
    result = app(con, surroundings, run).execute(KEY, ENTRY)
    assert result.execution is not None and result.execution.answer.kind == kind and len(run.calls) == 1
    assert run.calls[0][0].kind == harness

surroundings = attempt_surroundings


def test_native_id_adapter_preserves_uuid_and_token_formats() -> None:
    ids = NativeIds()
    hexadecimal, session = ids.hex(), ids.session()
    assert UUID(hex=hexadecimal).hex == hexadecimal and len(hexadecimal) == 32
    assert str(UUID(session)) == session and len(session) == 36
    for size in (8, 16):
        token = ids.token(size)
        assert len(token) == 2 * size and bytes.fromhex(token).hex() == token
