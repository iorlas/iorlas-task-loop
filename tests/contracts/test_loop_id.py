"""LOOPID (tl-9un.45): each supervisor lifetime has an opaque loop id, kept across its exec; a run records it (None for a hand run)."""
from pathlib import Path

from taskloop.adapters import childenv
from taskloop.app.run.layout import loop_id_of
from taskloop.contracts.env import Env
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.ids import new_loop_id
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.paths import ConfigDir


def test_a_new_loop_id_is_opaque_and_unique() -> None:
    a, b = new_loop_id(), new_loop_id()
    assert a != b and len(a) >= 12 and a.isalnum()


def test_a_run_records_the_loop_id_and_a_take_up_keeps_it(tmp_path: Path) -> None:
    where = RunLocator(ConfigDir(tmp_path))
    run = where.create("/repo", "b-1", 10.0, "repo-key", loop_id="abc123").manifest.run
    got = where.get(run)
    assert got is not None and got.manifest.loop_id == "abc123"
    assert where.take_up(run, "/repo", "b-1", 20.0).manifest.loop_id == "abc123"


def test_a_hand_run_has_no_loop_id(tmp_path: Path) -> None:
    run = RunLocator(ConfigDir(tmp_path)).create("/repo", "b-1", 10.0).manifest
    assert run.loop_id is None
    assert loop_id_of(Env({})) is None


def test_the_loop_id_of_a_run_is_the_one_its_loop_exported() -> None:
    assert loop_id_of(Env({EnvVar.TASK_LOOP_LOOP_ID.value: "abc123"})) == "abc123"


def test_the_loop_id_survives_the_loops_exec() -> None:
    env = Env({EnvVar.TASK_LOOP_LOOP_ID.value: "abc123"})
    assert childenv.exec_env(env, {EnvVar.TL_LOOP_STATE: "s"})[EnvVar.TASK_LOOP_LOOP_ID.value] == "abc123"
