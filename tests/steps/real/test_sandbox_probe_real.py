"""Real layer: the sandbox probe through the shelf's capture, with a stand-in `codex` (a shell script; the real one is the
owner-run live smoke's): what it is run with (the scratch as cwd, Codex's own environment, `sandbox` and the keys), how
its end maps to the answer, and that `access.PROBE` checks the shell's variables, removes its own folders and fails on
a root it cannot write."""

import json
import os
import stat
from pathlib import Path

import pytest

from taskloop.access import agent_env, folders
from taskloop.slot_env import sandbox_probe

# MODE=record: write the cwd, TMPDIR, UV_OFFLINE and every argument to $RECORD, then exit $RC.
# MODE=run: run what follows `--` (the probe itself, unsandboxed).
CODEX = """#!/bin/sh
if [ "$MODE" = run ]; then
  while [ "$1" != "--" ]; do shift; done
  shift
  exec "$@"
fi
printf '%s\\n' "$PWD" "$TMPDIR" "$UV_OFFLINE" "$@" > "$RECORD"
exit "$RC"
"""


@pytest.fixture
def codex(tmp_path: Path) -> str:
    path = tmp_path / "codex"
    path.write_text(CODEX)
    path.chmod(stat.S_IRWXU)
    return str(path)


@pytest.fixture
def slot(tmp_path: Path) -> Path:
    slot = tmp_path / "slots" / "0123456789ab" / "s1"
    slot.mkdir(parents=True)
    for root in folders(slot).roots:
        root.mkdir(parents=True)
    return slot


@pytest.mark.parametrize(("rc", "answer"), [(0, True), (1, False)])
def test_the_probe_runs_codex_sandbox_in_the_emptied_scratch_with_codexs_own_environment(
    codex: str, slot: Path, tmp_path: Path, rc: int, answer: bool
) -> None:
    """Codex itself gets the environment it is given (no TMPDIR of the roots); the shell's variables are its keys."""
    found, record = folders(slot), tmp_path / "record"
    env = {"PATH": os.environ["PATH"], "MODE": "record", "RECORD": str(record), "RC": str(rc)}
    assert sandbox_probe(codex, env, found) is answer
    lines = record.read_text().splitlines()
    assert lines[:4] == [str(found.tmp), "", "", "sandbox"]
    assert f"shell_environment_policy.set.TMPDIR={json.dumps(str(found.tmp))}" in lines
    assert lines[-3:] == [str(path) for path in found.roots]


def test_a_codex_that_cannot_start_is_a_failed_probe(slot: Path, tmp_path: Path) -> None:
    found = folders(slot)
    assert sandbox_probe(str(tmp_path / "missing"), {"PATH": os.environ["PATH"]}, found) is False


def test_a_shell_without_its_variables_fails_the_probe(codex: str, slot: Path) -> None:
    """A Codex config that overrides the shell's policy would leave the agent without TMPDIR or offline uv: exit 5."""
    found = folders(slot)
    assert sandbox_probe(codex, {"PATH": os.environ["PATH"], "MODE": "run"}, found) is False
    assert all(list(root.iterdir()) == [] for root in found.roots)


def test_the_probe_fails_on_a_root_it_cannot_write_and_leaves_nothing_behind(codex: str, slot: Path) -> None:
    """The stand-in passes the shell's variables as Codex would. A folder an earlier probe left (`.tl-probe-1`) is no
    obstacle: names are unpredictable. The first two roots get their folder made and removed; the third is read-only,
    so the probe stops with exit 3."""
    found = folders(slot)
    (found.cache / ".tl-probe-1").mkdir()
    found.tools.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        assert sandbox_probe(codex, {"PATH": os.environ["PATH"], "MODE": "run", **agent_env(found)}, found) is False
    finally:
        found.tools.chmod(stat.S_IRWXU)
    assert [list(root.iterdir()) for root in found.roots] == [[], [found.cache / ".tl-probe-1"], []]
