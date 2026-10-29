"""The process sim and its guard: a fake answers an argv in memory, a real spawn in a logic test fails it, real_proc turns the guard off."""
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
import stream_proc
from support import procsim
from support.procsim import real_proc


class Fakes(unittest.TestCase):
    def test_a_fake_answers_through_stream_proc_with_no_process(self):
        out = []
        cmd = procsim.fake("two-lines", procsim.exits(3, "a\nb"))
        res = stream_proc.run([cmd], cwd=".", on_stdout=out.append, timeout=5)
        self.assertEqual((res.returncode, "".join(out), procsim.ran(cmd)), (3, "a\nb\n", 1))

    def test_a_fake_past_the_wall_limit_is_stopped_there_without_sleeping(self):
        cmd = procsim.fake("sleeps-60", procsim.takes(60, out="started"))
        res = stream_proc.run([cmd], cwd=".", timeout=0.6)
        self.assertEqual((res.timed_out, res.returncode), ("wall", None))
        self.assertIsNone(stream_proc.run([cmd], cwd=".", timeout=61).timed_out)

    def test_env_words_before_a_fake_reach_it(self):
        procsim.fake("sees-foo", lambda cwd, env: (0 if env.get("FOO") == "1" else 1, ""))
        self.assertEqual(stream_proc.run(["env", "FOO=1", "sees-foo"], cwd=".").returncode, 0)

    def test_subprocess_run_gets_the_same_answer(self):
        r = subprocess.run(["true"], capture_output=True, text=True, check=False)
        self.assertEqual((r.returncode, r.stdout), (0, ""))


class Guard(unittest.TestCase):
    def test_a_planted_spawn_fails_the_test_naming_its_argv(self):
        with self.assertRaises(AssertionError) as caught:
            subprocess.run(["sleep", "0.01", "planted"], check=False)
        self.assertIn("spawned a real process: sleep 0.01 planted", str(caught.exception))
        with self.assertRaises(AssertionError):
            procsim.WORLD[-1].check()  # the teardown would fail this test too: the engine swallowing the error does not hide it
        procsim.WORLD[-1].problems.clear()

    def test_a_planted_spawn_through_the_streaming_runner_fails_too(self):
        with self.assertRaises(AssertionError):
            stream_proc.run(["sleep", "0.01"], cwd=".")
        procsim.WORLD[-1].problems.clear()

    def test_git_is_left_to_the_gitsim(self):
        self.assertEqual(subprocess.run(["git", "--version"], capture_output=True, check=False).returncode, 0)

    @real_proc("the guard is off for a test whose subject is the process")
    def test_a_marked_test_may_spawn(self):
        self.assertEqual(subprocess.run(["true"], check=False).returncode, 0)  # a fake still answers; a real command runs
        self.assertEqual(subprocess.run(["sleep", "0.01"], check=False).returncode, 0)


if __name__ == "__main__":
    unittest.main()
