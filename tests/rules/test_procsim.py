"""The process sim and its guard: a fake answers an argv in memory, a real spawn in a logic test fails it, real_proc turns the guard off."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stream_proc
import support.paths  # noqa: F401  (ROOT/src on sys.path)

from tltestkit import procsim


class Fakes(Case):
    def test_a_fake_answers_through_stream_proc_with_no_process(self):
        out = []
        cmd = procsim.fake("two-lines", procsim.exits(3, "a\nb"))
        res = stream_proc.run([cmd], cwd=".", on_stdout=out.append, timeout=5)
        assert (res.returncode, "".join(out), procsim.ran(cmd)) == (3, "a\nb\n", 1)

    def test_a_fake_past_the_wall_limit_is_stopped_there_without_sleeping(self):
        cmd = procsim.fake("sleeps-60", procsim.takes(60, out="started"))
        res = stream_proc.run([cmd], cwd=".", timeout=0.6)
        assert (res.timed_out, res.returncode) == ("wall", None)
        assert stream_proc.run([cmd], cwd=".", timeout=61).timed_out is None

    def test_env_words_before_a_fake_reach_it(self):
        procsim.fake("sees-foo", lambda cwd, env: (0 if env.get("FOO") == "1" else 1, ""))
        assert stream_proc.run(["env", "FOO=1", "sees-foo"], cwd=".").returncode == 0

    def test_subprocess_run_gets_the_same_answer(self):
        r = subprocess.run(["true"], capture_output=True, text=True, check=False)
        assert (r.returncode, r.stdout) == (0, "")


class Guard(Case):
    def test_a_planted_spawn_fails_the_test_naming_its_argv(self):
        with pytest.raises(AssertionError) as caught:
            subprocess.run(["sleep", "0.01", "planted"], check=False)
        assert "spawned a real process: sleep 0.01 planted" in str(caught.value)
        with pytest.raises(AssertionError):
            procsim.WORLD[-1].check()  # the teardown would fail this test too: the engine swallowing the error does not hide it
        procsim.WORLD[-1].problems.clear()

    def test_a_planted_spawn_through_the_streaming_runner_fails_too(self):
        with pytest.raises(AssertionError):
            stream_proc.run(["sleep", "0.01"], cwd=".")
        procsim.WORLD[-1].problems.clear()

    def test_a_planted_real_git_call_fails_the_test_too(self):
        with pytest.raises(AssertionError) as caught:
            subprocess.run(["git", "--version"], capture_output=True, check=False)
        assert "spawned a real process: git --version" in str(caught.value)
        procsim.WORLD[-1].problems.clear()

    def test_a_planted_fork_fails_the_test_too(self):
        with pytest.raises(AssertionError):
            os.fork()
        procsim.WORLD[-1].problems.clear()

    def test_a_real_test_that_never_spawned_fails(self):
        idle = procsim.Procs("tests/x/real/test_y.py::T::test_z", guarded=False)
        with pytest.raises(AssertionError) as caught:
            idle.check(must_spawn=True)
        assert "never started a process" in str(caught.value)
        idle.spawns = 1
        idle.check(must_spawn=True)
