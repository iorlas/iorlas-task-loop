"""A committed malicious profile cannot make the push judge execute a host command."""
import json
import sys
from pathlib import Path

from support.case import Case
from support.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401
from support import gitq
from support.engine_case import real_git
from support.memstores import fake_stores

from taskloop.adapters.git import RealGit
from taskloop.app.land.push_judge import PushStatus, judge_push
from tlkernel.env import snapshot


class PushPolicy(Case):
    @real_git("the judge must reject a real committed malicious profile without creating a canary outside its worktree")
    def test_tip_profile_cannot_execute_on_the_host(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "worktree"
            repo.mkdir()
            canary = root / "CANARY"
            gitq.git("init", "-q", "-b", "main", cwd=repo)
            for key, value in (("user.name", "t"), ("user.email", "t@x"), ("commit.gpgsign", "false")):
                gitq.git("config", key, value, cwd=repo)
            profile = repo / ".task-loop.json"
            profile.write_text(json.dumps({"engine": {"checks": [{"id": "gate", "argv": ["true"], "run": "gate"}]}}))
            gitq.git("add", ".task-loop.json", cwd=repo)
            gitq.git("commit", "-q", "-m", "trusted policy", cwd=repo)
            base = gitq.git("rev-parse", "HEAD", cwd=repo)
            assert base
            gitq.git("update-ref", "refs/remotes/origin/main", base, cwd=repo)
            malicious = {"engine": {"checks": [
                {"id": "gate", "argv": ["true"], "run": "gate"},
                {"id": "attack", "argv": ["touch", str(canary)], "run": "gate"}]}}
            profile.write_text(json.dumps(malicious))
            gitq.git("commit", "-q", "-a", "-m", "writer profile", cwd=repo)
            tip = gitq.git("rev-parse", "HEAD", cwd=repo)
            assert tip != base
            env = snapshot()

            decision = judge_push(str(repo), f"refs/heads/topic {tip} refs/heads/topic {'0' * 40}\n",
                                  fake_stores(), RealGit(env), env=env)
            assert decision.status == PushStatus.REFUSED
            assert decision.reasons[0].startswith("profile_changed: refs/heads/topic")
            assert not canary.exists()
