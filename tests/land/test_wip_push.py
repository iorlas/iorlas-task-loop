"""tl-7y6.22: an accepted stage is pushed to origin's task/<bead> (no hook, no -u, no git config); a failed push blocks; a custom land
command pushes nothing."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import gitq
from support.engine_case import EngineTest

from tltestkit.logs import records
from tltestkit.plans import CLEAN, PLAN, WRITE

# isort: split
from taskloop.adapters.git import RealGit
from taskloop.app.land.push import Outbound
from taskloop.app.run.engine import Engine
from tlkernel.gitfacts import GitOutcome

RUN = {"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}
WIP = ("origin", "HEAD:refs/heads/task/t-1")


class WipPush(EngineTest):
    def config(self):
        return (self.wt / ".git" / "config").read_text()

    def origin_ref(self, ref):
        return gitq.git("rev-parse", "--verify", "-q", ref, cwd=str(Path(self.tmp.name) / "o.git"))

    def test_an_accepted_stage_pushes_head_to_the_task_branch_without_upstream_or_config(self):
        before = self.config()
        seen = []
        real = RealGit.push_lease

        def spy(this, d, remote, refspec, expect):
            seen.append((remote, refspec))
            return real(this, d, remote, refspec, expect)

        def fetched(_git, wt, remote, ref):  # the engine's git is scripted here: read the real clone for what it last fetched
            return gitq.git("rev-parse", "--verify", "-q", f"refs/remotes/{remote}/{ref.removeprefix('refs/heads/')}", cwd=str(wt))

        with mock.patch.object(RealGit, "push_lease", spy), mock.patch("taskloop.app.land.push.last_fetched", fetched):
            rc, _ = self.run_engine(RUN)
        assert rc == 0, self.blocked
        assert seen == [WIP] * len(seen)
        assert seen
        assert not self.origin_ref("refs/heads/task/t-1")  # the land then deleted the pushed task branch (LANDBRANCH)
        assert self.config() == before

    def test_a_failed_push_blocks_the_bead_with_gits_words(self):
        out = GitOutcome(ok=False, output="fatal: unable to access 'https://x/r.git/': Could not resolve host: x")
        with mock.patch.object(RealGit, "push_lease", return_value=out):
            rc, _ = self.run_engine(RUN)
        assert rc != 0
        said = " ".join(r["text"] for r in records(self.eng, "warn"))
        assert "paused: the work-in-progress push" in said
        assert "Could not resolve host" in said
        assert not self.closed
        assert not self.origin_ref("refs/heads/task/t-1")

    def test_a_refused_push_is_a_land_fault(self):
        out = GitOutcome(ok=False, output=" ! [rejected] HEAD -> task/t-1 (stale info)\nerror: failed to push some refs")
        with mock.patch.object(RealGit, "push_lease", return_value=out):
            self.run_engine(RUN)
        said = " ".join(r["text"] for r in records(self.eng, "warn"))
        assert "holds work this clone has never fetched (another machine ran this bead)" in said
        asked = " ".join(str(c) for c in self.store.calls)
        assert "stale info" in asked
        assert "engine-fault" in asked

    def test_hook_refusal_and_complete_stage_push_output_are_kept(self):
        refusal = "gate: refusing the push: run just check"
        output = "progress\n" * 250 + refusal + "\n" + "progress\n" * 250 + "error: failed to push some refs\n"
        with mock.patch.object(RealGit, "push_lease", return_value=GitOutcome(ok=False, output=output)):
            rc, _ = self.run_engine(RUN)
        assert rc != 0
        files = list((self.eng.run_dir / "land-push").glob("*.log"))
        assert len(files) == 1
        assert files[0].read_text() == output
        closed = " ".join(r["why"] for r in records(self.eng, "close"))
        assert refusal in closed
        assert str(files[0]) in closed

    def test_a_custom_land_command_pushes_nothing(self):
        pushed = []
        real = Engine.sh

        def spy(this, cmd, *a, **kw):
            pushed.append(list(cmd))
            return real(this, cmd, *a, **kw)
        with mock.patch.object(Engine, "sh", spy):
            self.run_engine(RUN, land=["git", "log"])
        assert not [c for c in pushed if c[:2] == ["git", "push"]]
        assert not self.origin_ref("refs/heads/task/t-1")

    def test_an_lfs_repo_pushes_its_lfs_files_first(self):
        calls = []
        e = SimpleNamespace(
            dry=False,
            cfg=SimpleNamespace(land=["git", "push", "origin", "HEAD:main"]),
            wt=self.wt,
            bead="t-1",
            checkout=SimpleNamespace(stage_all=lambda: None),
            clock=SimpleNamespace(monotonic=lambda: 1.0),
            log=SimpleNamespace(note=lambda _m: None),
            steps=mock.Mock(),
            git=SimpleNamespace(
                staged=lambda _d: False,
                lfs_push=lambda d, r, refs: calls.append(("lfs", r, *refs)) or GitOutcome(ok=True, output=""),
                rev_parse=lambda d, rev: "",
                push_lease=lambda d, r, spec, expect: calls.append(("push", r, spec)) or GitOutcome(ok=True, output=""),
            ),
        )
        (self.wt / ".gitattributes").write_text("*.bin filter=lfs diff=lfs merge=lfs -text\n")
        with mock.patch("taskloop.app.land.push.shutil.which", return_value="/usr/bin/git-lfs"):
            Outbound(e).wip_push(1)
        assert [c[0] for c in calls] == ["lfs", "push"]

    def test_a_dry_run_pushes_nothing(self):
        e = SimpleNamespace(dry=True, cfg=SimpleNamespace(land=["git", "push", "origin", "HEAD:main"]), sh=mock.Mock(), git=mock.Mock())
        Outbound(e).wip_push(1)
        e.sh.assert_not_called()
