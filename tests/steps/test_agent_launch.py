"""Released harness launch specs, local credentials and the shared strict answer path, without vendor execution."""

import json
from pathlib import Path
from uuid import UUID

import pytest
from any_agent import LaunchInputs, LaunchSpec, OpenCodeHarness, RunOutcome, Summary
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

SAVED_SESSION = "saved-session-reference"


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


@pytest.mark.parametrize("harness", list(HarnessKind))
@pytest.mark.parametrize("prepared", [False, True])
def test_native_continuation_keeps_the_saved_session(tmp_path: Path, harness: HarnessKind, prepared: bool) -> None:
    files = EvidenceFiles(tmp_path)
    contract = {"type": "object", "properties": {}}
    schema, out = files.prepare(KEY, contract)
    root = files.launch_root(KEY)
    slot = tmp_path / "slot"
    credentials = (f"/bin/{harness}", {"HOME": str(tmp_path)})
    ids = FixedIds()
    result = AgentLaunch(lambda _kind: credentials, ids=ids).build(
        setting(harness, tmp_path), slot, prepared, root, schema, out, "Continue task", resume=SAVED_SESSION,
    )
    assert isinstance(result, LaunchedAgent)
    try:
        argv = result.spec.argv
        assert ids.sessions == [] and result.harness.evidence.ref == SAVED_SESSION
        assert result.credentials == credentials and result.spec.cwd == str(slot)
        expected = "Continue task\nReturn exactly one JSON object satisfying this answer schema:\n" + Path(schema).read_text()
        assert result.spec.stdin == expected
        assert argv[0] == credentials[0] and "chosen" in argv
        if harness is HarnessKind.CODEX:
            assert argv[1:3] == ["exec", "resume"] and argv[-2:] == [SAVED_SESSION, "-"]
            assert argv[argv.index("--output-schema") + 1] == schema and argv[argv.index("-o") + 1] == out
            assert 'model_reasoning_effort="medium"' in argv and (result.probe is not None) is prepared
            result.harness.parse_line(json.dumps({"type": "thread.started", "thread_id": SAVED_SESSION}))
        elif harness is HarnessKind.CLAUDE:
            assert argv[argv.index("--resume") + 1] == SAVED_SESSION and "--session-id" not in argv
            assert argv[argv.index("--permission-mode") + 1] == "dontAsk" and "--json-schema" in argv
            assert json.loads(argv[argv.index("--settings") + 1]) == {"env": {"OPAQUE": "value"}}
        else:
            assert argv[argv.index("--session") + 1] == SAVED_SESSION
            assert Path(result.spec.env["SHELL"]) == root / f"opencode-shell-{SAVED_SESSION[:8]}.sh"
            assert "edit" not in json.loads(result.spec.env["OPENCODE_CONFIG_CONTENT"])["permission"]
        assert result.harness.summary(0, "", "", None, False).res["ref"] == SAVED_SESSION
    finally:
        result.harness.cleanup()


@pytest.mark.parametrize("harness", list(HarnessKind))
def test_ordinary_builds_allocate_fresh_sessions(tmp_path: Path, harness: HarnessKind) -> None:
    files = EvidenceFiles(tmp_path)
    schema, out = files.prepare(KEY, {"type": "object"})
    ids = FixedIds()
    adapter = AgentLaunch(lambda kind: (f"/bin/{kind}", {"HOME": str(tmp_path)}), ids=ids)
    for _ in range(2):
        result = adapter.build(setting(harness, tmp_path), tmp_path, False, files.launch_root(KEY), schema, out, "Task")
        assert isinstance(result, LaunchedAgent)
        try:
            assert not {"resume", "--resume", "--session"}.intersection(result.spec.argv)
            expected_ref = ids.sessions[-1] if harness is HarnessKind.CLAUDE else None
            assert result.harness.evidence.ref == expected_ref
        finally:
            result.harness.cleanup()
    assert len(ids.sessions) == len(set(ids.sessions)) == 2


@pytest.mark.parametrize("sandbox", [CodexSandbox.WORKSPACE_WRITE, CodexSandbox.DANGER_FULL_ACCESS])
@pytest.mark.parametrize("prepared", [False, True])
@pytest.mark.parametrize("host_tmp", [None, "/host/scratch"], ids=["unset", "conflicting_host"])
@pytest.mark.parametrize("resume", [None, SAVED_SESSION])
def test_codex_launch_limits_automatic_context_and_preserves_access(
    tmp_path: Path, sandbox: CodexSandbox, prepared: bool, host_tmp: str | None, resume: str | None,
) -> None:
    files = EvidenceFiles(tmp_path)
    schema, out = files.prepare(KEY, {"type": "object", "properties": {}})
    chosen = AgentSetting(model="chosen", access=CodexPolicy(sandbox=sandbox))
    credentials = {"HOME": str(tmp_path)}
    if host_tmp is not None:
        credentials["TMPDIR"] = host_tmp
    adapter = AgentLaunch(lambda kind: (f"/bin/{kind}", credentials), ids=NativeIds())
    slot = tmp_path / "slots" / "repo" / "s1"
    result = adapter.build(chosen, slot, prepared, files.launch_root(KEY), schema, out, "Task input", resume=resume)
    assert isinstance(result, LaunchedAgent)
    try:
        argv = result.spec.argv
        settings = dict(item.split("=", 1) for index, item in enumerate(argv) if index and argv[index - 1] == "-c")
        assert settings["skills.include_instructions"] == "false"
        assert settings["features.multi_agent"] == "false"
        assert settings["features.recommended_plugins"] == "false"
        prefix = "shell_environment_policy.set."
        shell_env = {key.removeprefix(prefix): json.loads(value) for key, value in settings.items() if key.startswith(prefix)}
        expected = {"TMPDIR": str(slot.parent / ".t" / "s1"),
                    "UV_CACHE_DIR": str(slot.parent / ".env" / "s1" / "uv-cache"),
                    "UV_TOOL_DIR": str(slot.parent / ".env" / "s1" / "uv-tools"), "UV_OFFLINE": "1"}
        assert shell_env == (expected if prepared else {})
        assert result.spec.env == credentials
        if resume is None:
            assert argv[argv.index("-s") + 1] == sandbox
        else:
            assert json.loads(settings["sandbox_mode"]) == sandbox and "-s" not in argv
        assert 'approval_policy="never"' in argv and "tool_output_token_limit=3000" in argv
        assert "--ignore-user-config" in argv and "--ignore-rules" in argv
        if sandbox is CodexSandbox.DANGER_FULL_ACCESS:
            assert result.probe is None and not any("sandbox_workspace_write" in item for item in argv)
        else:
            assert (result.probe is not None) is prepared
            assert json.loads(settings["sandbox_workspace_write.writable_roots"]) == (list(expected.values())[:3] if prepared else [])
            assert settings["sandbox_workspace_write.network_access"] == "false"
            assert settings["sandbox_workspace_write.exclude_slash_tmp"] == "true"
            assert settings["sandbox_workspace_write.exclude_tmpdir_env_var"] == "true"
    finally:
        result.harness.cleanup()


@pytest.mark.parametrize("harness", list(HarnessKind))
@pytest.mark.parametrize("resume", ["", " ", "saved session", "saved\n", "\tsaved", "--last", "-session"])
def test_invalid_continuation_is_explained_without_allocating_a_session(
    tmp_path: Path, harness: HarnessKind, resume: str,
) -> None:
    ids = FixedIds()
    result = AgentLaunch(lambda kind: (f"/bin/{kind}", {}), ids=ids).build(
        setting(harness, tmp_path), tmp_path, False, tmp_path, "unused", "unused", "Task", resume=resume,
    )
    assert isinstance(result, LaunchFailure) and result.reason == "launch:ValueError"
    assert "session reference" in result.explanation and ids.sessions == []


@pytest.mark.parametrize("resume", [None, SAVED_SESSION])
def test_failed_preparation_cleans_up_harness_resources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resume: str | None) -> None:
    launch_spec = OpenCodeHarness.launch_spec
    shells: list[Path] = []

    def fail_after_preparation(harness: OpenCodeHarness, inputs: LaunchInputs) -> LaunchSpec:
        spec = launch_spec(harness, inputs)
        shell = Path(spec.env["SHELL"])
        assert shell.exists()
        shells.append(shell)
        raise ValueError("preparation failed")

    monkeypatch.setattr(OpenCodeHarness, "launch_spec", fail_after_preparation)
    files = EvidenceFiles(tmp_path)
    schema, out = files.prepare(KEY, {"type": "object"})
    result = AgentLaunch(lambda _kind: ("/bin/opencode", {"HOME": str(tmp_path)}), ids=FixedIds()).build(
        setting(HarnessKind.OPENCODE, tmp_path), tmp_path, False, files.launch_root(KEY), schema, out, "Task", resume=resume,
    )
    assert isinstance(result, LaunchFailure) and result.reason == "launch:ValueError" and result.explanation
    assert len(shells) == 1 and not shells[0].exists()


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
