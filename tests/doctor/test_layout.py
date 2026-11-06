"""LAYOUTDOCTOR (tl-9un.32) and LEAKCHECK (tl-9un.37): `tl doctor` lists where a repo deviates from tl's layout and what of the factory
leaked into it. Read-only: nothing is removed. A compliant repo gets no line."""
from pathlib import Path
from types import SimpleNamespace

from taskloop.domain.layout import matchers as layout
from taskloop.app.wire import doctor
from taskloop.contracts import config


def profile(*checks: dict, slots: dict | None = None) -> config.RepoProfile:
    return config.load({"engine": {"checks": list(checks)}, "slots": slots or {}})


GOOD = {"id": "unit", "argv": ["run-tests", "--out", "$TL_ARTIFACT_DIR/unit.xml"], "inputs": ["src/**"]}


def test_a_compliant_repo_gets_no_line() -> None:
    assert layout.deviations(profile(GOOD)) == []
    assert layout.leaks(["src/a.py", "README.md"], lambda p: "print('hi')") == []


def test_a_check_that_writes_outside_the_artifact_dir_is_listed() -> None:
    bad = {"id": "build", "argv": ["builder", "-logFile", "Logs/build.log"], "inputs": ["src/**"]}
    out = layout.deviations(profile(GOOD, bad))
    assert len(out) == 1 and "check build" in out[0] and "Logs/build.log" in out[0] and "TL_ARTIFACT_DIR" in out[0]


def test_a_keep_glob_that_leaves_the_tree_is_listed() -> None:
    bad = {"id": "t", "argv": ["x", "$TL_ARTIFACT_DIR/o"], "keep": ["../elsewhere/*.xml"], "inputs": ["src/**"]}
    out = layout.deviations(profile(bad))
    assert len(out) == 1 and "keep" in out[0] and "../elsewhere/*.xml" in out[0]


def test_checks_that_never_name_the_artifact_dir_are_one_missing_opt_in() -> None:
    plain = {"id": "lint", "argv": ["lint", "."], "inputs": ["src/**"]}
    out = layout.deviations(profile(plain))
    assert len(out) == 1 and "TL_ARTIFACT_DIR" in out[0] and "opt" in out[0]


def test_a_journal_file_and_a_tl_variable_in_a_tool_are_two_findings(tmp_path: Path) -> None:
    files = {"notes/journal.md": "day 1", "tools/run.sh": "echo $TL_ARTIFACT_DIR", "src/a.py": "x = 1"}
    out = layout.leaks(list(files), files.__getitem__)
    assert len(out) == 2
    assert any("notes/journal.md" in line and "journal" in line for line in out)
    assert any("tools/run.sh" in line and "TL_ARTIFACT_DIR" in line for line in out)


def test_the_profile_and_prose_are_not_tools() -> None:
    files = {".task-loop.json": "TL_X", "docs/x.md": "TASK_LOOP_Y in prose"}
    assert layout.leaks(list(files), files.__getitem__) == []


def test_tracked_scratch_folder_stamp_and_tl_wording_are_listed() -> None:
    files = {".task/t-1/brief.md": "b", "build/gate.stamp": "ok", "ci/go.py": "# run by the task-loop"}
    out = layout.leaks(list(files), files.__getitem__)
    assert len(out) == 3


def test_doctor_wires_both_into_its_warnings(tmp_path: Path) -> None:
    (tmp_path / "run.sh").write_text("echo $TL_RUN_ID")
    (tmp_path / "journal.md").write_text("x")
    git = SimpleNamespace(ls_files=lambda repo: ["run.sh", "journal.md"])
    out = doctor.layout_warnings(str(tmp_path), (profile(GOOD), "main", "abc"), git)  # type: ignore[arg-type]
    assert len(out) == 2
