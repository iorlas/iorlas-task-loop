"""An engine push land cleans a real bare remote, with compare-oid leases even across cleanup retries."""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401
from support import gitq
from support.engine_case import CLEAN, PLAN, WRITE, EngineTest, real_git
from support.logs import records

# isort: split
from taskloop.app.land import cleanup
from taskloop.app.land.push import Pusher

RUN = {"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}


class EngineCleanup(EngineTest):
    def linked(self):
        """Run the engine in a linked checkout, so removing it cannot remove the main clone."""
        main = self.wt
        linked = Path(self.tmp.name) / "linked"
        gitq.git("worktree", "add", "--detach", str(linked), "HEAD", cwd=main)
        self.wt = linked
        return main

    @real_git("engine push to a bare origin, then leased remote deletion and linked checkout removal")
    def test_engine_push_land_removes_remote_local_and_worktree_after_recording_receipt(self):
        main = self.linked()
        rc, _ = self.run_engine(RUN)
        self.assertEqual(rc, 0, self.blocked)
        self.assertFalse(self.wt.exists())
        self.assertEqual(gitq.git("branch", "--list", "task/t-1", cwd=main), "")
        self.assertEqual(gitq.git("ls-remote", "origin", "refs/heads/task/t-1", cwd=main), "")
        self.assertTrue(records(self.eng, "land_receipt"))
        done = records(self.eng, "land_cleanup")[-1]
        self.assertEqual((done["local_outcome"], done["remote_outcome"]), ("gone", "gone"))

    @real_git("a remote task ref moves after the engine push checked it: force-with-lease must preserve it")
    def test_remote_that_moves_after_the_push_check_is_kept_on_retry(self):
        main = self.linked()
        pushing = Pusher.push
        moved = []

        def push(this, *args):
            got = pushing(this, *args)
            if isinstance(got, str) and got:
                # The pre-land WIP and the landed commit differ: put newer work on the remote task ref after the check.
                gitq.git("push", "-q", "origin", f"+{got}:refs/heads/task/t-1", cwd=main)
                moved.append(got)
            return got

        with mock.patch.object(Pusher, "push", push):
            rc, _ = self.run_engine(RUN)
        self.assertEqual(rc, 0, self.blocked)
        self.assertTrue(moved)
        cleanup.retry_logged(self.eng.git, self.eng.log)
        self.assertEqual(gitq.git("ls-remote", "origin", "refs/heads/task/t-1", cwd=main).split()[0], moved[0])
        done = records(self.eng, "land_cleanup")[-1]
        self.assertEqual((done["local_outcome"], done["remote_outcome"]), ("gone", "pending"))

    @real_git("an already-deleted task ref is success even when the original explicit lease is stale")
    def test_remote_already_gone_is_success(self):
        main = self.linked()
        retry = cleanup.retry

        def gone(git, log, row):
            if row.remote_outcome == "pending":
                gitq.git("push", "-q", "origin", ":refs/heads/task/t-1", cwd=main)
            return retry(git, log, row)

        with mock.patch.object(cleanup, "retry", gone):
            rc, _ = self.run_engine(RUN)
        self.assertEqual(rc, 0, self.blocked)
        self.assertFalse(self.wt.exists())
        done = records(self.eng, "land_cleanup")[-1]
        self.assertEqual((done["local_outcome"], done["remote_outcome"]), ("gone", "gone"))
