"""tools/experiment without live agents: arm building over a fake process port, randomization, the neutral profile, the
runner's verdict from state and the report's numbers."""

import json
import shutil
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

import pytest
from stream_proc import Captured

from exp_arms import Builder, Paths, SetupFailed, config_text, neutral_profile
from exp_order import describe, plan
from exp_report import arm_table, denominators, report, summary
from exp_run import Runner
from exp_spec import Arm, Outcome, Run, RunResult, Spec, Task

PROFILE = {
    "checks": [{"name": "check", "argv": ["just", "check"], "timeout": 1}],
    "required": ["check"],
    "land": "auto",
}


@pytest.fixture
def short() -> Iterator[Path]:
    """A short folder: the factory limits a slot path to 64 bytes and pytest's tmp_path is longer."""
    root = Path(tempfile.mkdtemp(dir="/tmp"))
    yield root
    shutil.rmtree(root, ignore_errors=True)


def spec_in(root: Path, tasks: int = 3, **changes: object) -> Spec:
    work = root
    texts = []
    for number in range(tasks):
        text = work / f"t{number}.txt"
        text.parent.mkdir(parents=True, exist_ok=True)
        text.write_text(f"text {number}")
        texts.append(Task(id=f"tl-t{number}", title=f"title {number}", text_file=text))
    values: dict[str, object] = {
        "name": "exp",
        "source": work / "source",
        "base": "b" * 40,
        "engine": work / "engine",
        "work": root / "w",
        "tasks": tuple(texts),
        "arms": {"a": Arm(), "b": Arm(workflow="other", efforts={"implement": "low"})},
        "seed": 7,
    }
    return Spec.model_validate({**values, **changes})


class FakeProc:
    """Answers each command by its words; `git clone <origin> <repo>` makes the clone with the base profile."""

    def __init__(self, rows: object = None, rounds_exit: int = 0, timed_out: bool = False) -> None:
        self.calls: list[tuple[list[str], Mapping[str, str] | None]] = []
        self.rows, self.rounds_exit, self.timed_out = rows, rounds_exit, timed_out

    def __call__(self, argv: Sequence[str], *, cwd: Path | None = None, env: Mapping[str, str] | None = None, timeout: float) -> Captured:
        words = list(argv)
        self.calls.append((words, env))
        out = b""
        if words[:2] == ["git", "clone"] and "--bare" not in words:
            Path(words[-1]).mkdir(parents=True)
            Path(words[-1], ".task-loop.json").write_text(json.dumps(PROFILE))
        elif "rev-parse" in words:
            out = b"c" * 40 + b"\n"
        elif "adopt" in words:
            Path(words[words.index("--db") + 1]).write_text("")
        elif "rounds" in words:
            return Captured(self.rounds_exit, b"", b"boom", 1.0, self.timed_out)
        elif "list" in words:
            out = json.dumps({"attempts": self.rows}).encode()
        elif "export" in words:
            out = b"[]"
        return Captured(0, out, b"", 0.1, False)


def test_the_plan_is_seeded_and_has_one_run_of_every_arm_per_task(tmp_path: Path) -> None:
    spec = spec_in(tmp_path)
    runs = plan(spec)
    assert runs == plan(spec)
    for block in range(1, 4):
        assert sorted(each.arm for each in runs if each.block == block) == ["a", "b"]
    assert sorted(each.task for each in runs) == sorted(task.id for task in spec.tasks for _arm in spec.arms)
    assert describe(runs).count("\n") == 3


def test_every_arm_order_appears_across_seeds(tmp_path: Path) -> None:
    first = {plan(spec_in(tmp_path, seed=seed))[0].arm for seed in range(20)}
    assert first == {"a", "b"}


def test_the_neutral_profile_wraps_each_check_and_never_lands() -> None:
    wrapped = neutral_profile(PROFILE, Path("/empty/.beads"))
    assert wrapped["land"] == "manual" and wrapped["required"] == ["check"]
    assert wrapped["checks"] == [{"name": "check", "argv": ["env", "BEADS_DIR=/empty/.beads", "just", "check"], "timeout": 1}]
    assert PROFILE["land"] == "auto"


def test_the_config_writes_each_arms_efforts(tmp_path: Path) -> None:
    spec = spec_in(tmp_path)
    run = Run(name="tl-t0_b", task="tl-t0", arm="b", block=1, position=0)
    text = config_text(spec, run, Paths(spec, run))
    assert "slot_count = 1" in text and '[agents.implement]\neffort = "low"' in text
    assert "[agents" not in config_text(spec, run.model_copy(update={"arm": "a"}), Paths(spec, run))


def test_building_an_arm_makes_origin_clone_neutral_commit_tracker_and_slot(short: Path) -> None:
    spec, proc = spec_in(short), FakeProc()
    run = Run(name="tl-t0_a", task="tl-t0", arm="a", block=1, position=0)
    base = Builder(spec, proc).arm(run)
    paths = Paths(spec, run)
    assert base == "c" * 40 and paths.origin.name == "aa.git" and paths.slot == paths.slots / "aa" / "s1"
    profile = json.loads((paths.repo / ".task-loop.json").read_text())
    assert profile["land"] == "manual" and profile["checks"][0]["argv"][:2] == ["env", f"BEADS_DIR={short / 'w/emptybeads/.beads'}"]
    words = [" ".join(call[:6]) for call, _env in proc.calls]
    assert any("update-ref refs/heads/main " + "b" * 40 in line for line in words)
    created = next(call for call, _env in proc.calls if "create" in call)
    assert created[created.index("--id") + 1] == "tl-t0" and "text 0" in created
    assert all("MISE_TRUSTED_CONFIG_PATHS" in (env or {}) for _call, env in proc.calls)
    assert all("BEADS_DIR" not in (env or {}) for call, env in proc.calls if call[0] == "bd")
    with pytest.raises(SetupFailed, match="already exists"):
        Builder(spec, proc).arm(run)


def test_a_slot_path_over_the_limit_is_refused_before_anything_is_built(short: Path) -> None:
    spec = spec_in(short, work=short / ("w" * 40))
    run = Run(name="tl-t0_a", task="tl-t0", arm="a", block=1, position=0)
    with pytest.raises(SetupFailed, match="over 64"):
        Builder(spec, FakeProc()).arm(run)
    assert not Paths(spec, run).root.exists()


@pytest.mark.parametrize(
    "rows, outcome",
    [
        ([{"status": "waiting_for_land", "hold": False}], Outcome.PASS),
        ([{"status": "done", "hold": True}], Outcome.HELD),
        ([{"status": "running", "hold": False}], Outcome.INCOMPLETE),
    ],
)
def test_a_run_ends_with_the_rounds_and_its_verdict_comes_from_state(short: Path, rows: list[dict[str, object]], outcome: Outcome) -> None:
    spec, proc = spec_in(short, tasks=1), FakeProc(rows)
    run = Run(name="tl-t0_a", task="tl-t0", arm="a", block=1, position=0)
    found = Runner(spec, proc, lambda: 5.0).one(run, 2)
    assert found.outcome is outcome and found.in_flight_planned == 2
    started = next(call for call, _env in proc.calls if "rounds" in call)
    assert "--exit-when-idle" in started and "--workflow" in started and "default" in started


@pytest.mark.parametrize("code, capped, outcome", [(0, True, Outcome.CAP_WALL), (1, False, Outcome.INFRA)])
def test_a_capped_or_failed_rounds_process_is_its_own_outcome(short: Path, code: int, capped: bool, outcome: Outcome) -> None:
    run = Run(name="tl-t0_a", task="tl-t0", arm="a", block=1, position=0)
    found = Runner(spec_in(short), FakeProc(rounds_exit=code, timed_out=capped), lambda: 5.0).one(run, 1)
    assert found.outcome is outcome


def result(arm: str, task_total: float | None, t_in: int | None, cached: int | None, outcome: Outcome = Outcome.PASS) -> RunResult:
    rows: list[dict[str, object]] = [
        {"step": "plan", "wall_seconds": 10, "t_in": t_in, "t_cached": cached, "t_out": 1, "turns": 2, "rework_count": 0},
        {"step": "implement", "wall_seconds": 20, "t_in": t_in, "t_cached": cached, "t_out": 3, "turns": 4, "rework_count": 0,
         "task_total_seconds": task_total, "failed_checks": ["lint"]},
    ]  # fmt: skip
    return RunResult(run=Run(name=f"t_{arm}{task_total}", task="t", arm=arm, block=1, position=0), outcome=outcome, export=rows)


def test_summary_reports_n_and_leaves_unknown_out() -> None:
    assert summary([]) == "n=0" and summary([2.0]) == "n=1 mean 2 median 2 sd -"
    assert summary([1.0, 3.0]) == "n=2 mean 2 median 2 sd 1"


def test_the_report_separates_uncached_from_cached_and_plan_from_implement() -> None:
    results = [result("a", 100, 1000, 900), result("a", 300, 3000, 2000), result("b", 50, 500, 100), result("b", None, None, None)]
    table = arm_table(results, ["a", "b"])
    assert "n=2 mean 200 " in table.split("| task total s |")[1].split("\n")[0]  # a: 100 and 300
    assert "| plan wall s |" in table and "| implement wall s |" in table and "| input cached |" in table
    assert "n=1 mean" in table.split("| task total s |")[1].split("\n")[0]  # b: the unknown run is out


def test_the_report_counts_holds_and_caps_as_results(tmp_path: Path) -> None:
    results = [result("a", 1, 1, 0), result("a", 2, 1, 0, Outcome.HELD), result("b", 3, 1, 0, Outcome.CAP_WALL)]
    text = denominators(results, ["a", "b"])
    assert "| a | 2 | 1 | 1 | 0 | 0 | 0 | 0 |" in text and "| b | 1 | 0 | 0 | 0 | 1 | 0 | 0 |" in text
    spec = spec_in(tmp_path)
    document = report(spec, results, "t: a b\n")
    assert document.startswith("# exp: report") and "lint" in document and "`" + "b" * 40 + "`" in document
