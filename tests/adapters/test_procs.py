"""The process seam (adapters/procs.py): the child env a worker gets, a captured run, a stopped tree, and the SIGTERM that lands while a
child is being spawned (the engine's handler raises: the child must not be left running, owned by nobody)."""
import os
import unittest

import support.paths  # noqa: F401

from taskloop.adapters import childenv

POSIX = os.name != "nt"




class Interrupted(Exception):
    """What the engine's SIGTERM handler raises."""


class ChildEnv(unittest.TestCase):
    def test_a_session_identity_is_dropped_and_a_custom_claude_login_is_kept(self):
        env = {"ANTHROPIC_BASE_URL": "x", "CLAUDE_CODE_SESSION_ID": "s", "CLAUDE_CONFIG_DIR": "/home/u/.claude-alt", "TASK_LOOP_STATE": "x",
               "GIT_DIR": "/x", "GIT_INDEX_FILE": "/i", "OPENAI_API_KEY": "k", "PATH": "/bin"}
        out = childenv.child_env_of(env)
        self.assertEqual(out["CLAUDE_CONFIG_DIR"], "/home/u/.claude-alt")  # a worker on a custom login finds it
        for gone in ("ANTHROPIC_BASE_URL", "CLAUDE_CODE_SESSION_ID", "TASK_LOOP_STATE", "GIT_DIR", "GIT_INDEX_FILE"):
            self.assertNotIn(gone, out)
        self.assertEqual((out["OPENAI_API_KEY"], out["PATH"]), ("k", "/bin"))  # credentials stay: delegate scrubs its workers itself
        self.assertEqual((out["DELEGATE_DEPTH"], out["TASK_LOOP_WORKER"]), ("1", "1"))


if __name__ == "__main__":
    unittest.main()
