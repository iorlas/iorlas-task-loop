"""The PR-mode land (`land_mode: pr`): the branch goes up, a PR is opened, the bead waits as a typed ask; merged -> the PR's merge commit is
the landing; closed unmerged -> a typed ask. The engine never merges: the forge fake fails the test on `gh pr merge`."""
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.fake_beads import FakeBeads
from support.fakegit import ScriptedGit
from support.forgesim import ForgeSim

from tltestkit.narrow import must

# isort: split
from support.memstores import fake_stores

from taskloop.app.land import pr_land
from taskloop.app.land.forge import peek
from taskloop.app.land.gate import Problem, ProblemKind, mint
from taskloop.app.land.host import Land
from taskloop.app.land.pr_land import PrLand
from taskloop.stores.runlog import RunLog
from tlasks import pr_wake, raiser
from tlkernel import askspecs as specs
from tlkernel import fence, scratch
from tlkernel.ask import Ask
from tlkernel.askenums import AskClass, AskStatus
from tlkernel.bead import Bead
from tlkernel.config import load
from tlkernel.forge import PR_NUMBER, PR_URL
from tlkernel.gitfacts import GitOutcome, LogRow
from tlkernel.ids import BeadId, TreeSha
from tlkernel.kinds import Kind
from tlkernel.runkey import BaseSha
from tlpipeline.api import Blocked, blocked_for

BEAD = BeadId("t-1")
BRANCH = "task/t-1"
HEAD = "h" * 40
MERGE = "m" * 40


class NeverMerges(ForgeSim):
    """The forge as the engine sees it: a `gh pr merge` (or an auto-merge) fails the test. The owner merges through `owner_merges`."""

    def run(self, argv, **kw):
        if argv[:3] == ["gh", "pr", "merge"] or "--auto" in argv:
            pytest.fail(f"the engine merged: {' '.join(argv)}")
        return super().run(argv, **kw)

    def owner_merges(self, number: int) -> None:
        self.prs[number].update(state="MERGED", mergeCommit={"oid": MERGE})

    def owner_closes(self, number: int) -> None:
        self.prs[number]["state"] = "CLOSED"


class Git(ScriptedGit):
    def __init__(self, sim: NeverMerges) -> None:
        super().__init__()
        self.sim, self.head = sim, HEAD

    def rev_parse(self, d, rev):
        if rev.startswith("refs/remotes/"):
            return ""
        return {"HEAD": self.head, "HEAD^{tree}": "tree", "origin/main": "base"}[rev]

    def log(self, d, include, exclude=None, limit=0, grep=""):
        return [LogRow(oid=self.head, time=0, subject="Do it (t-1)")]

    def push_lease(self, d, remote, refspec, expect_sha):
        ran = self.sim.run(["git", "push", remote, refspec])
        return GitOutcome(ok=ran.exit == 0, output=ran.err)

    def ls_remote(self, d, remote, *patterns):
        return []


class Steps:
    def __init__(self):
        self.outcomes = []

    def outcome(self, outcome, detail=""):
        self.outcomes.append((outcome, detail))


class Checkout:
    def fetch(self, check=False):
        return 0, ""


class World(Case):
    def setup_method(self):
        self.sim = NeverMerges()
        self.git = Git(self.sim)
        self.store = FakeBeads()
        self.store.beads[BEAD] = Bead(id=BEAD, title="T", status="in_progress")
        run_dir = scratch.scratch_dir(os.environ)
        self.addCleanup(shutil.rmtree, run_dir, True)
        self.host = SimpleNamespace(
            bead=BEAD, cfg=SimpleNamespace(base="origin/main", land=["git", "push", "origin", "HEAD:main"]), spawner=self.sim,
            log=RunLog(fake_stores().run_log("r"), run_id="r", host="h"), run_dir=Path(run_dir), git=self.git, wt="/wt",
            store=self.store, claim=fence.offline(BEAD), steps=Steps(), checkout=Checkout(), task_branch=BRANCH, landed_sha="",
            blocked_for=blocked_for)
        self.pr = PrLand(self.host)

    def opened(self) -> Blocked:
        return self.push()

    def push(self, tree: str = "tree", base: str = "base") -> Blocked:
        with pytest.raises(Blocked) as stop:
            self.pr.push(Land(), mint(TreeSha(tree), BaseSha(base)))
        return stop.value

    def meta(self) -> dict:
        return self.store.beads[BEAD].metadata


class Opening(World):
    def test_the_gated_tip_is_pushed_a_pr_opened_and_the_bead_asks_the_owner(self):
        stop = self.opened()
        assert stop.kind is Kind.ASK_DECISION
        spec = must(stop.spec)
        assert spec.ask_class is AskClass.PR_OPEN
        assert spec.detail.text == "https://x/o/r/pull/1"
        assert self.sim.remote[BRANCH] == HEAD
        assert self.sim.ran("gh pr create")[0].split()[:5] == ["gh", "pr", "create", "--head", BRANCH]
        assert (self.meta()[PR_NUMBER], self.meta()[PR_URL]) == ("1", "https://x/o/r/pull/1")

    def test_a_pass_for_another_tree_is_stale_and_nothing_is_sent(self):
        got = self.pr.push(Land(), mint(TreeSha("other"), BaseSha("base")))
        assert isinstance(got, Problem)
        assert got.kind is ProblemKind.STALE
        assert self.sim.calls == []

    def test_a_second_push_updates_the_same_pr_and_opens_no_second(self):
        self.opened()
        self.git.head = "n" * 40
        self.opened()
        assert len(self.sim.ran("gh pr create")) == 1
        assert self.sim.prs[1]["headRefOid"] == "n" * 40

    def test_a_failed_branch_push_is_a_fault_and_opens_no_pr(self):
        self.sim.fail["git push"] = 1
        with pytest.raises(Blocked) as stop:
            self.pr.push(Land(), mint(TreeSha("tree"), BaseSha("base")))
        assert stop.value.kind is Kind.FAULT_LAND
        assert self.sim.ran("gh") == []

    def test_a_gh_failure_is_a_fault(self):
        self.sim.fail["gh pr create"] = 1
        with pytest.raises(Blocked) as stop:
            self.pr.push(Land(), mint(TreeSha("tree"), BaseSha("base")))
        assert stop.value.kind is Kind.FAULT_LAND


class Settling(World):
    def test_no_pr_means_nothing_to_settle(self):
        assert self.pr.settled() == ""

    def test_an_open_pr_on_the_same_head_asks_again(self):
        self.opened()
        with pytest.raises(Blocked) as stop:
            self.pr.settled()
        assert must(stop.value.spec).ask_class is AskClass.PR_OPEN

    def test_an_open_pr_after_new_work_lands_again(self):
        self.opened()
        self.git.head = "n" * 40
        assert self.pr.settled() == ""

    def test_a_merged_pr_is_the_landing_with_its_own_merge_commit(self):
        self.opened()
        self.sim.owner_merges(1)
        assert self.pr.settled() == MERGE
        assert self.host.landed_sha == MERGE
        assert self.host.steps.outcomes == [("landed", MERGE[:12])]
        assert PR_NUMBER in self.meta()  # still there until the land is recorded and synced
        self.pr.done()
        assert PR_NUMBER not in self.meta()
        assert PR_URL not in self.meta()

    def test_a_pr_merged_before_the_push_is_seen_is_the_landing(self):
        self.sim.pr(1, BRANCH, HEAD, state="MERGED")
        self.sim.owner_merges(1)
        assert self.pr.push(Land(), mint(TreeSha("tree"), BaseSha("base"))) == MERGE

    def test_a_pr_closed_without_a_merge_is_a_typed_ask_and_forgotten(self):
        self.opened()
        self.sim.owner_closes(1)
        with pytest.raises(Blocked) as stop:
            self.pr.settled()
        assert stop.value.kind is Kind.ASK_DECISION
        assert must(stop.value.spec).ask_class is AskClass.PR_CLOSED
        assert PR_NUMBER not in self.meta()
        assert self.pr.settled() == ""  # the next run lands again with a new PR

    def test_the_engine_never_calls_the_forge_merge(self):
        source = Path(pr_land.__file__).read_text()
        assert not any(word in source for word in (".merge(", '"merge"', "--auto"))


def asking(sim_state: str):
    """A PR_OPEN ask on t-1 whose PR (7) is `sim_state`, a bd with the bead blocked, and the asks."""
    asks, store = fake_stores().asks, FakeBeads()
    store.beads[BEAD] = Bead(id=BEAD, title="T", status="blocked", metadata={PR_NUMBER: "7"})
    at = raiser.Asking(bead=BEAD, run="r", brief_hash="b", repo="/repo", title="T", now=1)
    ask = must(raiser.raise_ask(asks, specs.pr_open(BEAD, 7, "https://x/o/r/pull/7"), at)[0])
    sim = NeverMerges()
    sim.pr(7, BRANCH, HEAD, state=sim_state)
    return asks, store, sim, ask


class Waking(Case):
    def wake(self, state: str, asks, store, sim):
        cfg = load({}).engine
        return pr_wake.wake_decided(asks, store, lambda n: peek(sim, "/repo", n), "/repo", 5.0, cfg)

    def test_a_merged_pr_answers_the_ask_and_opens_the_bead(self):
        asks, store, sim, _ = asking("MERGED")
        assert self.wake("MERGED", asks, store, sim) == [BEAD]
        done: Ask = must(asks.get(BEAD))
        answer = must(done.answer)
        assert (done.status, answer.action, answer.text, answer.by) == (AskStatus.ANSWERED, "rerun", "merged", "engine:pr")
        assert store.beads[BEAD].status == "open"

    def test_a_closed_pr_wakes_the_bead_too(self):
        asks, store, sim, _ = asking("CLOSED")
        assert self.wake("CLOSED", asks, store, sim) == [BEAD]  # (closed: the rerun's land raises the typed ask)
        assert must(must(asks.get(BEAD)).answer).text == "closed"

    def test_an_open_pr_wakes_nothing(self):
        asks, store, sim, _ = asking("OPEN")
        assert self.wake("OPEN", asks, store, sim) == []
        assert must(asks.get(BEAD)).answer is None
        assert store.beads[BEAD].status == "blocked"

    def test_a_forge_that_does_not_answer_wakes_nothing(self):
        asks, store, sim, _ = asking("MERGED")
        sim.fail["gh pr view"] = 1
        assert self.wake("MERGED", asks, store, sim) == []

    def test_other_asks_are_left_alone(self):
        asks, store, sim, ask = asking("MERGED")
        asks.put(ask.replace(ask_class=AskClass.OPEN_QUESTION))
        assert self.wake("MERGED", asks, store, sim) == []
        assert sim.ran("gh pr merge") == []
