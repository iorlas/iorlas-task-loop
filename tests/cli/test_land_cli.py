"""`tl step land` (tl-8bh9.14.8 slice L5) through `main`: the flags become one `LandRequest` for the one operation
(`land.land` over `cli_composition.open_land`, both replaced here), every answer's text, exit code and JSON keys (results
made by `land_bench`'s real operation), the land's own guide before the step commands', printable details, and a guide
for every refusal word the land's modules write."""

import ast
import json
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Literal

import pytest
from git_porcelain import RemoteRejected, Transient
from land_bench import LandBench, bench

from taskloop import cli_composition, cli_step
from taskloop import land as land_module
from taskloop.cli import main
from taskloop.git_views import GitViews
from taskloop.land import Landed, LandRequest
from taskloop.land_check import LandPorts
from taskloop.land_close import NOT_SYNCED
from taskloop.land_guide import INTERRUPTED, LAND_GUIDE
from taskloop.land_push import Withdrawn
from taskloop.land_render import HOW
from taskloop.land_summary import LandSummary
from taskloop.operations import Failed
from taskloop.result_data import Result
from taskloop.step_guide import GUIDE
from taskloop.validate import RELAUNCHED

LAND = ["step", "land", "tl-1", "--backlog", "tasks", "--checkout", "/checkout", "--minutes", "20"]
SOURCES = Path(__file__).resolve().parents[2] / "src" / "taskloop"
type How = Literal["pushed", "already_pushed", "no_change", "delivered", "already_landed"]
HOWS: tuple[How, ...] = ("pushed", "already_pushed", "no_change", "delivered", "already_landed")
CANDIDATE = {"candidate_id", "number", "checks_attempt_id", "origin", "commit", "tree_same", "required", "slot", "slot_head", "deadline",
             "validation", "reason", "validated_at", "released_at", "parked", "superseded", "delivery", "delivered_at", "remote_head",
             "close", "closed_at", "land_process"}


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every command resolves the machine config: under tmp_path, never the real ~/.config or ~/.local."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return tmp_path / "home"


@pytest.fixture
def b(tmp_path: Path) -> LandBench:
    (tmp_path / "bench").mkdir()
    return bench(tmp_path / "bench")


def run(argv: list[str], result: Result, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> tuple[int, str, str]:
    monkeypatch.setitem(cli_step.OPERATIONS, ("step", "land"), lambda _arguments, _loaded: result)
    code = main(argv)
    output = capsys.readouterr()
    return code, output.out, output.err


@pytest.mark.parametrize(("flags", "mode", "no_change"), [
    ([], "land", False), (["--summary"], "summary", False), (["--withdraw"], "withdraw", False), (["--no-change"], "land", True),
    (["--summary", "--no-change"], "summary", True),
], ids=["land", "summary", "withdraw", "no_change", "summary_no_change"])
def test_the_flags_become_one_land_request_for_the_one_operation(
    flags: list[str], mode: Literal["land", "summary", "withdraw"], no_change: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    opened: list[tuple[Path, Path]] = []
    requests: list[LandRequest] = []
    ports = object()

    @contextmanager
    def open_land(database: Path, artifacts: Path, _views: GitViews) -> Generator[object]:
        opened.append((database, artifacts))
        yield ports

    def operation(given: LandPorts, request: LandRequest) -> Failed:
        assert given is ports
        requests.append(request)
        return Failed("refused", "choices", "stubbed")

    monkeypatch.setattr(cli_composition, "open_land", open_land)
    monkeypatch.setattr(land_module, "land", operation)
    assert main([*LAND, *flags, "--db", str(tmp_path / "f.db"), "--artifacts", str(tmp_path / "art")]) == 1
    assert opened == [(tmp_path / "f.db", tmp_path / "art")]
    assert requests == [LandRequest("tasks", "tl-1", Path("/checkout"), 20, mode, no_change)]
    assert capsys.readouterr().err.startswith("tl step land: refused:choices\nstubbed\n")


@pytest.mark.parametrize("argv", [
    [*LAND, "--summary", "--withdraw"], LAND[:-2], [part for part in LAND if part not in ("--checkout", "/checkout")],
], ids=["summary_and_withdraw", "no_minutes", "no_checkout"])
def test_usage_errors_exit_2_before_any_operation(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_composition, "open_land", lambda *_: pytest.fail("opened"))
    with pytest.raises(SystemExit) as ended:
        main(argv)
    assert ended.value.code == 2


def test_an_absent_factory_db_is_refused_and_none_is_created(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*LAND, "--db", str(tmp_path / "none.db"), "--artifacts", str(tmp_path / "art")]) == 1
    assert capsys.readouterr().err.startswith("tl step land: refused:database") and not (tmp_path / "none.db").exists()


def test_the_help_names_the_flags_and_exit_codes(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["step", "land", "-h"])
    text = " ".join(capsys.readouterr().out.split())
    assert all(flag in text for flag in ("--summary", "--withdraw", "--no-change", "--minutes", "--checkout", "--backlog"))
    assert "never forced" in text and "rounds never land" in text and "Exit 0 landed (or already), 1 refused, 3 unknown" in text


def test_a_land_prints_what_it_did_the_close_and_the_tracker_line(
    b: LandBench, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    found = b.land()
    assert isinstance(found, Landed)
    row = found.row
    code, out, err = run(LAND, found, capsys, monkeypatch)
    assert (code, err) == (0, "")
    assert out.splitlines() == [
        f"pushed: tl-1 (backlog tasks) on origin main; {HOW['pushed']}",
        f"Candidate 1 ({row.key.attempt_id}): S {row.commit} onto origin main at {b.base}; same tree as X, no checks",
        f"Pushed: origin main at {row.commit}", "Closed: closed", NOT_SYNCED, "Next: `git pull --ff-only` in your checkout.",
    ]
    code, out, _ = run([*LAND, "--json"], found, capsys, monkeypatch)
    data = json.loads(out)
    assert code == 0 and set(data) == {"status", "backlog", "task", "candidate", "release", "synced"}
    assert set(data["candidate"]) == CANDIDATE and (data["status"], data["synced"]) == ("pushed", False)
    assert (data["candidate"]["delivery"], data["candidate"]["close"]) == ("pushed", "closed")


@pytest.mark.parametrize("how", HOWS)
def test_every_way_a_land_ends_says_what_this_call_did(
    how: How, b: LandBench, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    found = b.land()
    assert isinstance(found, Landed)
    code, out, _ = run(LAND, replace(found, how=how, release="held:slot_dirty"), capsys, monkeypatch)
    assert code == 0 and out.startswith(f"{how}: tl-1 (backlog tasks) on origin main; {HOW[how]}\n") and "Release: held:slot_dirty" in out


def test_a_land_whose_close_is_still_to_come_says_so_and_no_tracker_line(
    b: LandBench, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    found = b.land()
    assert isinstance(found, Landed)
    code, out, _ = run(LAND, replace(found, row=replace(found.row, close=None, closed_at=None), how="delivered"), capsys, monkeypatch)
    assert code == 0 and "Closed: not yet: rerun `tl step land` to close the task (the code is on main)." in out and NOT_SYNCED not in out


def test_a_withdrawal_and_a_summary_exit_0_with_their_lines_and_keys(
    b: LandBench, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = b.land("summary")
    assert isinstance(summary, LandSummary)
    code, out, _ = run([*LAND, "--summary"], summary, capsys, monkeypatch)
    assert code == 0 and out.startswith("Checks: checks passed at X") and "same tree as X, no checks" in out
    assert out.rstrip().endswith("Nothing was recorded, reserved, pushed or closed: `tl step land TASK` lands it.")
    data = json.loads(run([*LAND, "--summary", "--json"], summary, capsys, monkeypatch)[1])
    assert (data["status"], data["state"], data["again"], data["added"]) == ("summary", "same_tree", False, [])
    b.repo.answer = Transient("connection reset")
    assert isinstance(b.land(), Failed)
    withdrawn = b.land("withdraw")
    assert isinstance(withdrawn, Withdrawn)
    code, out, _ = run([*LAND, "--withdraw"], withdrawn, capsys, monkeypatch)
    assert code == 0 and out.startswith(f"withdrawn: tl-1 (backlog tasks); candidate 1 ({withdrawn.row.key.attempt_id}) superseded")
    data = json.loads(run([*LAND, "--withdraw", "--json"], withdrawn, capsys, monkeypatch)[1])
    assert set(data) == {"status", "backlog", "task", "candidate"} and data["candidate"]["superseded"] == "withdrawn"


@pytest.mark.parametrize(("failed", "code"), [
    (Failed("refused", "conflict", "X does not merge"), 1), (Failed("refused", "claim_lost", "taken"), 1),
    (Failed("unavailable", "checks:running", "a check runs"), 3), (Failed("unsettled", "check_running", "held"), 3),
    (Failed("unavailable", "target_moved", "moved"), 3), (Failed("refused", "remote_rejected", "protected"), 1),
], ids=["conflict", "claim_lost", "checks_running", "held", "target_moved", "remote_rejected"])
def test_a_refusal_exits_1_an_unknown_3_on_stderr_with_the_land_s_guide_first(
    failed: Failed, code: int, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    found, out, err = run(LAND, failed, capsys, monkeypatch)
    lines = err.splitlines()
    assert (found, out) == (code, "") and lines[:2] == [f"tl step land: {failed.word}", failed.detail]
    key = next(each for each in (failed.reason, failed.reason.split(":")[0], failed.kind) if each in LAND_GUIDE)
    assert LAND_GUIDE[key] in lines and (key not in GUIDE or GUIDE[key] not in lines)  # never the step commands' meaning
    assert (LAND_GUIDE["unavailable"] in lines) is (failed.kind == "unavailable")
    data = json.loads(run([*LAND, "--json"], failed, capsys, monkeypatch)[2])
    assert data == {"error": {"kind": failed.kind, "reason": failed.reason, "message": failed.detail}}


def test_a_ctrl_c_during_a_land_is_one_interrupted_answer_exit_130_not_a_traceback(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    @contextmanager
    def open_land(_database: Path, _artifacts: Path, _views: GitViews) -> Generator[object]:
        yield object()

    def interrupted(_ports: LandPorts, _request: LandRequest) -> Failed:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_composition, "open_land", open_land)
    monkeypatch.setattr(land_module, "land", interrupted)
    argv = [*LAND, "--db", str(tmp_path / "f.db"), "--artifacts", str(tmp_path / "art")]
    assert main(argv) == 130
    output = capsys.readouterr()
    assert output.out == "" and output.err.splitlines() == [
        f"tl step land: unavailable:{INTERRUPTED}", LAND_GUIDE[INTERRUPTED], LAND_GUIDE["unavailable"]]
    assert main([*argv, "--json"]) == 130
    assert json.loads(capsys.readouterr().err) == {"error": {"kind": "unavailable", "reason": INTERRUPTED, "message": None}}


@pytest.mark.parametrize("reason", ["target_moved", "remote_rejected"])
def test_a_moved_main_or_a_remote_refusal_says_the_fact_then_a_guide_that_adds_to_it(
    reason: str, b: LandBench, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    if reason == "target_moved":
        b.racing = lambda: b.advance({"OTHER": "another task\n"})
    else:
        b.repo.answer = RemoteRejected("[remote rejected] main (protected branch hook declined)")
    found = b.land()
    assert isinstance(found, Failed) and found.reason == reason
    _, _, err = run(LAND, found, capsys, monkeypatch)
    detail, guide = err.splitlines()[1:3]
    row = b.rows()[0]
    assert row.commit in detail and detail.endswith("nothing was pushed." if reason == "target_moved" else "stays validated.")
    assert guide == LAND_GUIDE[reason] and guide.startswith(("Rerun `tl step land`", "Push S by hand"))
    assert not {each.strip(" .").lower() for each in detail.split(";")} & {each.strip(" .").lower() for each in guide.split(";")}
    assert "protected branch" not in err  # origin's own text is never printed (`land_push`)


def test_a_detail_is_printed_as_printable_lines(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    failed = Failed("refused", "blocked", "bd says:\x1b[31m cannot close\r\nNext: landed\u2028forged")
    _, _, err = run(LAND, failed, capsys, monkeypatch)
    lines = err.splitlines()
    assert lines[1:3] == ["bd says: [31m cannot close", "Next: landed forged"] and all(line.isprintable() for line in lines)


def _literals(names: tuple[str, ...], call: str, position: int) -> set[str]:
    """The literal word at `position` of every `call(...)` in the named modules (both branches of a conditional)."""
    found: set[str] = set()
    for name in names:
        for node in ast.walk(ast.parse((SOURCES / f"{name}.py").read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == call and len(node.args) > position:
                word = node.args[position]
                choices = (word.body, word.orelse) if isinstance(word, ast.IfExp) else (word,)
                found |= {each.value for each in choices if isinstance(each, ast.Constant) and isinstance(each.value, str)}
    return found


LANDS = ("land", "land_check", "land_push", "land_close", "land_summary", "land_store")
# The words a land passes through from its collaborators (the `Failed(kind, reason)` built from another value): the
# candidate release's (`NotReleased`, the park's `slot_<state>`, `repo`, `not_listed`), the stores' fences
# (`StoreRefused`), the slot choice and the checkout (`AdmitRefused`/`AdmitUnavailable`), the profile at O, the
# validation's relaunchable words, and the kinds. An agent attempt's release words (`worker_*`) and the checks
# admission's `task_attempted` never reach it.
PASSED = {"slot_redirected", "repo", "not_listed", "checkout", "deadline", "expired", "no_free_slot", "git", "store", "target",
          "target_profile", "no_required", "checks", "environment", "refused", "unavailable", "unsettled"}
AGENT_ONLY = {"worker_alive", "worker_unknown", "task_attempted"}


def _words() -> set[str]:
    """Every refusal or unknown word a land answers, written by its modules or passed through from its collaborators."""
    written = _literals(LANDS, "Failed", 1)
    released = _literals(("slot_release", "check_release"), "NotReleased", 1)
    fenced = _literals(("land_store", "check_store", "setup_store"), "StoreRefused", 0)
    return (written | released | fenced | PASSED | set(RELAUNCHED)) - AGENT_ONLY


def test_every_word_the_land_answers_has_the_land_s_own_guide() -> None:
    words = _words()
    assert {"push_barred", "land_running", "slot_branch", "slot_unborn", "absent", "land_changed", "stale_reservation"} <= words
    assert sorted(words - LAND_GUIDE.keys()) == []
    assert sorted(word for word in ("checks", "slot_busy", "claim_lost", "remote_rejected", "target", "no_required", "branch_moved",
                                    "commit_missing", "remote", "changed", "no_free_slot") if LAND_GUIDE[word] == GUIDE.get(word)) == []
