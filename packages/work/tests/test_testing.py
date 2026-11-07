"""Recording fakes satisfy stage protocols and drive actual work code."""
from pathlib import Path

import pytest
from tlkernel.asked import Asked, Updates
from tlkernel.bead import Bead
from tlkernel.checks import CheckResult, CheckRun
from tlkernel.config import CheckSpec, EngineConfig, HostResources
from tlkernel.gitfacts import DiffEntry
from tlkernel.gitport import Git
from tlkernel.ids import CheckId
from tlkernel.kinds import Kind
from tlkernel.plancheck import PlanData
from tltestkit.cfgs import plan_of
from tltestkit.plans import PLAN, WRITE

from tlwork.look.host import LookHost, LookPorts
from tlwork.plan.host import PlanHand, PlanPorts
from tlwork.review.host import ReviewHand, ReviewPorts
from tlwork.testing import FakeLook, FakePlan, FakeReview, FakeWrite
from tlwork.testing_memory import FakeChecks, FakeLeftovers
from tlwork.testing_parts import FakeLinks, WorkStop
from tlwork.write.check_round import CheckRound
from tlwork.write.host import WriteHost
from tlwork.write.review_round import ReviewRound
from tlwork.write.stage_loop import StageLoop
from tlwork.write.state import RoundResult, RoundStop, StageState
from tlwork.write.write_round import WriteRound


def test_protocols_and_isolated_handoffs(workdir: Path) -> None:
    plan, look, review, write = FakePlan(workdir), FakeLook(workdir), FakeReview(workdir), FakeWrite(workdir)
    pp: PlanPorts = plan.ports
    ph: PlanHand = plan.hand
    lp: LookPorts = look.ports
    lh: LookHost = look.hand
    rp: ReviewPorts = review.ports
    rh: ReviewHand = review.hand
    wh: WriteHost = write
    git: Git = plan.ports.git
    assert pp.store is plan.ports.store and lp.pictures is look.pictures and rp.checkout is review.ports.checkout
    assert ph.leftovers == rh.leftovers == lh.leftovers == wh.leftovers == []
    ph.leftovers.append({"title": "later"})
    assert rh.leftovers == lh.leftovers == wh.leftovers == []
    with pytest.raises(AssertionError, match="unexpected git fetch"):
        git.fetch("/wt")


def test_ai_shell_clock_and_stops(workdir: Path) -> None:
    p = FakePlan(workdir).ports
    first = Asked(data={"summary": "one"}, family="claude", updates=Updates())
    p.answers.append(first)
    assert p.ai("plan", "title", "prompt", "arg", round=2) is first
    assert p.asked == [("plan", "title", "prompt", ("arg",), {"round": 2})]
    with pytest.raises(AssertionError, match="no AI answer"):
        p.ai("plan", "empty", "")
    p.shell_answers.extend([(0, "saved"), (1, "bad")])
    target = workdir / "out"
    assert p.sh(["fake"], save=target, network=True) == (0, "saved")
    assert target.read_text() == "saved" and p.commands[0][1]["network"] is True
    with pytest.raises(AssertionError, match="command failed"):
        p.sh(["fake"], check=True)
    with pytest.raises(AssertionError, match="no shell answer"):
        p.sh(["fake"])
    p.comment("c")
    p.warn("w")
    p.assumed("a")
    p.publish_plan()
    assert (p.comments, p.warned, p.assumptions, p.published) == (["c"], ["w"], ["a"], 1)
    before = p.now()
    p.clock.advance(2)
    assert p.now() == before + 2
    stop = p.blocked_for("why", "NOOP")
    assert isinstance(stop, WorkStop) and (stop.why, stop.kind) == ("why", Kind.NOOP)


def test_steps_logs_and_checkpoints(workdir: Path) -> None:
    p = FakePlan(workdir).ports
    assert p.log.note("n") == 0 and p.log.warn("w") == 0
    assert p.log.notes == ["n"] and p.log.warnings == ["w"]
    assert p.steps.begin("plan", "p", round=1) == 0
    p.steps.outcome("ok")
    p.steps.move("write", "ready")
    p.steps.end("pass")
    assert p.steps.calls == [("begin", ("plan", "p"), {"round": 1}), ("outcome", ("ok", ""), {}),
                             ("move", ("write", "ready", ""), {}), ("end", ("pass",), {})]
    assert not p.checkpoints.amend(lambda ck: ck.replace(n=1))
    p.checkpoints.save(step="plan", n=2)
    assert p.checkpoints.amend(lambda ck: ck.replace(n=3))
    ck = p.checkpoints.read()
    assert ck is not None and (ck.n, ck.t, ck.run) == (3, p.now(), p.facts.run_id)
    p.checkpoints.keep_pending("scope")
    p.checkpoints.keep_look()
    assert p.checkpoints.kept == ["pending:scope", "look"]


def test_memory_stores_keying_and_documents(workdir: Path) -> None:
    a, b = FakePlan(workdir).ports, FakePlan(workdir).ports
    stores = a.stores
    assert stores.check_run("r", None) is stores.check_run("r", None)
    assert stores.check_run("r", 1) is not stores.check_run("r", None)
    run = CheckRun(round=1, results=[])
    stores.check_run("r", None).write(run)
    assert stores.check_run("r", None).get() == run and b.stores.check_run("r", None).get() is None
    assert stores.adrs("repo") is stores.adrs("repo") and stores.adrs("other") is not stores.adrs("repo")
    assert stores.host.need() is None
    stores.host.write(HostResources())
    assert stores.host.need() == HostResources()
    a.store.put(Bead(id=a.facts.bead, title="work", status="open"))
    assert a.store.show(a.facts.bead) is not None and b.store.show(a.facts.bead) is None
    assert stores.tickets is not b.stores.tickets


def test_checkout_git_and_probe(workdir: Path) -> None:
    p = FakePlan(workdir).ports
    p.checkout.paths.append("f")
    p.checkout.changed_paths().clear()
    assert p.checkout.changed_paths() == ["f"]
    p.checkout.diff = "patch"
    assert p.checkout.task_diff() == "patch"
    assert p.checkout.base_sha() == "base" and p.checkout.tree_hash() == ""
    assert p.checkout.slot_status() == ([], [], "patch")
    p.git.replies[("diff",)] = ["one", "two"]
    p.git.replies[("diff", "base")] = "specific"
    assert p.git.diff("/wt", "base", "tip") == "specific"
    assert p.git.diff("/wt", "other", "tip") == "one"
    assert p.git.diff("/wt", "other", "tip") == "two"
    with pytest.raises(AssertionError, match="no reply scripted"):
        p.git.diff("/wt", "other", "tip")
    assert p.git.ls_tree("/wt", "base") == [] and p.git.grep("/wt", "x") == []
    assert p.git.calls[0] == ("diff", "base", "tip")
    probe = p.shell_probe()
    probe.files.add("f")
    probe.dirs.add("d")
    assert probe.has_command("true") and not probe.has_command("missing")
    assert probe.exists("f") and probe.exists("d") and not probe.is_dir("f") and probe.is_dir("d")
    assert probe.recipes() is None
    probe.recipe_names = {"test"}
    names = probe.recipes()
    assert names is not None and names == {"test"}
    names.clear()
    assert probe.recipes() == {"test"}


def test_plan_cases_briefs_and_noop_policy(workdir: Path) -> None:
    p = FakePlan(workdir)
    p.hand.plan_data = plan_of(PLAN)
    data = PlanData(summary="done", stages=[], leftovers=[{"title": "later", "why": "outside"}])
    p.planner.add_leftovers(data)
    p.planner.add_leftovers(data)
    assert p.hand.leftovers == data["leftovers"]
    with pytest.raises(WorkStop) as caught:
        p.planner.finished_work(data, False)
    assert caught.value.kind == Kind.NOOP and p.ports.published == 1
    bead = Bead(id=p.facts.bead, title="Task", status="open", description="Do work")
    assert "Do work" in p.briefs.fit(bead, [], "", 0).text
    assert p.ports.routing.ledger().deferred() == [("later", "outside")]
    assert p.ports.routing.ledger_of(data).deferred() == [("later", "outside")]


def test_review_verifier_and_link_findings(workdir: Path) -> None:
    r = FakeReview(workdir)
    assert r.routing.add_leftover({"title": "later", "why": "outside"})
    assert not r.routing.add_leftover({"title": "later"})
    assert r.verifier.run([]) == [] and r.ports.asked == []
    assert r.verifier.run([{"what": "nobody ran ruff on tools/*.py", "kind": "tooling"}]) == []
    assert r.live.verified[0]["why"] == "not a check here"
    r.live.link_bad["https://example.org"] = "HTTP 404"
    answer = {"findings": []}
    r.link_check.report([("README.md", "source", "https://example.org")], answer)
    assert "HTTP 404" in str(answer)
    assert r.ports.fixer.fix("test", "tail") == "accept"
    assert r.ports.fixer.calls == [("test", "tail", False)]
    assert not r.ports.judge.is_look({}) and r.ports.judge.look_verdict({}, "v", {}, "why") == ("v", {}, "why")
    assert r.ports.on_path("missing") is None


def test_links_and_leftover_modes() -> None:
    links = FakeLinks()
    links.found.append(("README.md", "source", "url"))
    links.answers["url"] = (False, "offline")
    links.offline.add("offline")
    assert links.added_urls("patch") == [("README.md", "source", "url")]
    assert links.check_all(["url"]) == {"url": (False, "offline")}
    assert links.check_all(["url"], fn=lambda url: (True, "")) == {"url": (True, "")}
    assert links.network_down("offline") and not links.network_down("404")
    assert links.calls == ["patch", "url"]
    rows: list[dict[str, object]] = []
    sink = FakeLeftovers(rows)
    assert sink.add_keyed("b", {"title": "first"}) and not sink.add_keyed("b", {"title": "second"})
    sink.extend([{"title": "first"}])
    assert len(rows) == 2


def test_look_pictures_and_collaborators(workdir: Path) -> None:
    look = FakeLook(workdir)
    p = look.ports
    pic = workdir / "raw.png"
    pic.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 50)
    base = workdir / "base"
    look.hand.artifact_repo = "repo"
    look.pictures.keep_picture(pic, [], base, 2)
    assert p.downscale.calls == [(pic, base / "raw.png", look.facts.cfg.look_max_px)]
    assert look.pictures.shots() == ["raw.png"]
    assert look.pictures.keep_evidence() == [look.facts.run_dir / "evidence" / "raw.png"]
    assert p.warned == []
    p.cases.case_list["taste"] = ["looks right"]
    assert p.cases.cases_of("taste") == ["looks right"]
    with p.waits.locked("look", workdir, "owner") as held:
        assert held == workdir
    assert p.waits.calls == [("look", workdir, "owner")]
    before = p.ports.repo.calls
    assert p.ports.repo.key() == "repo-key" and p.ports.repo.calls == before + 1


def test_queued_checks_record_options() -> None:
    fake = FakeChecks()
    fake.answers.extend([CheckRun(round=n, results=[]) for n in (1, 2, 3)])
    assert fake.run_items([], clean=True).round == 1
    assert fake.stoppable({"goal": "g", "files": [], "checks": []}, "stage", round=2).round == 2
    assert fake.requested([CheckId("lint")], "stage", round=3).round == 3
    assert fake.calls[0][2]["clean"] is True
    assert fake.calls[2] == ("requested", (["lint"], "stage"), {"round": 3})
    with pytest.raises(AssertionError, match="no check answer"):
        fake.run_items([])


@pytest.mark.parametrize("rc", [0, 1, 124])
def test_write_requests_prompts_and_result_handoff(workdir: Path, rc: int) -> None:
    cfg = EngineConfig(checks=[CheckSpec(id=CheckId("build"), argv=["build"], requestable=True)])
    w = FakeWrite(workdir, cfg)
    s = StageState(plan_of(PLAN), 0, None)
    s.w = dict(WRITE, run_checks=["build"])
    WriteRound(w).requests(s)
    w.stage_checks.answers.extend([CheckRun(round=1, results=[]), CheckRun(round=2, results=[CheckResult(
        id=CheckId("build"), cmd="build", group="tests", exit=rc, status="passed" if rc == 0 else "failed", tail="compiler output")])])
    result = CheckRound(w).run(s)
    assert result.flow == "" and result.run is not None and result.run.round == 1
    assert w.stage_checks.calls[1][1][0] == ["build"]
    prompt, delta = WriteRound(w).prompts(s, False)
    assert "Requested engine checks (informational)" in prompt and delta is None
    assert "cannot run requestable engine checks yourself" in prompt
    assert w.hand.calls[-1][6] == s.request_feedback and "compiler output" in s.request_feedback
    assert "compiler output" in prompt
    assert StageLoop(w).play(lambda st: RoundResult(rounds=1, summary="done", family="codex"), s) == ""
    assert (w.stats["rounds"], w.write.last_summary, w.writer_family) == (1, "done", "codex")


def test_write_trustroots_park_before_review(workdir: Path) -> None:
    w = FakeWrite(workdir)
    w.store.put(Bead(id=w.bead, title="Task", status="open"))
    w.git.replies[("merge_base",)] = "base"
    w.git.replies[("tree_of",)] = "tree"
    w.git.replies[("diff_entries",)] = (DiffEntry(status="M", path="AGENTS.md"),)
    with pytest.raises(RoundStop) as caught:
        ReviewRound(w).run(StageState(plan_of(PLAN), 0, None))
    assert isinstance(caught.value.cause, WorkStop)
    assert caught.value.cause.kind == Kind.ASK_DECISION and caught.value.cause.spec is not None
    assert w.asked == []


def test_named_text_ask_and_picture_collaborators(workdir: Path) -> None:
    p = FakePlan(workdir).ports
    p.shared.value = "shared"
    p.hand.value = "rounds"
    assert p.shared.shared_text() == "shared" and p.hand.rounds_text() == "rounds"
    assert p.briefing.where("write", ["check"], listed=["check"]) == ""
    assert p.briefing.calls == [("write", ("check",), None, ("check",))]
    assert p.ask_flow.repo() == "repo"
    assert p.ask_flow.raise_soft("q", None, "cause", "default") is None
    assert p.ask_flow.calls == [("q", None, "cause", "default")]
    assert p.pictures.visual_cfg() is None and p.pictures.shot_methods() == {} and p.pictures.shot_table() == ""
    p.pictures.mark_stale()
    assert p.pictures.stale
    assert str(p.move_host(["display"], "needs display")) == "needs display"
    w = FakeWrite(workdir)
    w.hand.add_flakes([{"what": "flake"}])
    w.hand.note_round("stage", 1, "red")
    w.hand.note_lows([{"what": "low"}])
    assert len(w.hand.calls) == 3
    assert w.hand.accepted_text() == w.hand.so_far_text() == w.hand.seen_lows_text() == w.hand.flakes_text() == ""
    w.cases.add_cases([{"criterion": "case"}])
    assert w.cases.added == [{"criterion": "case"}]
    assert w.cases.cases_text() == w.cases.plan_text() == w.cases.rules_text() == ""
    assert w.cases.out_of_scope([{"what": "x"}]) == w.cases.engine_unproven([{"what": "x"}], []) == [{"what": "x"}]
    w.ask_flow.review_cap(3)
    w.reload.safe_point("write")
    w.link_check.link_judged({"findings": []})
    assert w.reload.calls == [("review_cap", 3), ("safe_point", "write"), ("link_judged", {"findings": []})]
    assert w.newfiles.new_by_kind() == {"ignored": [], "meant": [], "unexplained": []}
    assert w.newfiles.stage_work([], []) == w.newfiles.new_files_brief([]) == ""
    assert w.newfiles.undecided_new(["f"], {}) == ["f"]
    with pytest.raises(AssertionError, match="must not run a process"):
        w.spawner.run(["fake"])


def test_pictures_refusal_cap_and_shared_content(workdir: Path) -> None:
    src = workdir / "raw.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 50)
    kept: list[Path] = []
    for run in ("t-1-first", "t-1-second"):
        look = FakeLook(workdir, run_id=run)
        look.hand.artifact_repo = "repo"
        look.pictures.keep_picture(src, [], workdir / "base", 1)
        kept.extend(look.pictures.keep_evidence())
    assert len(kept) == 2 and kept[0].stat().st_ino == kept[1].stat().st_ino
    capped = FakeLook(workdir / "cap", EngineConfig(evidence_cap_mb=0))
    capped.pictures.keep_picture(src, [], workdir / "base", 1)
    assert not capped.pictures.shots() and "1 file(s) not kept" in capped.ports.log.notes[0]
    invalid = workdir / "bad.png"
    invalid.write_bytes(b"invalid")
    look.pictures.keep_picture(invalid, [], workdir / "base", 2)
    assert "not registered" in look.ports.warned[0]
