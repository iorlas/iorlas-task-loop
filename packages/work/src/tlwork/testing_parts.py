"""Small configurable collaborators; no engine or application adapters."""
import contextlib
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

from tlkernel.askspec import AskSpec
from tlkernel.checkpoint import BriefSnap, PlanStep
from tlkernel.checks import CheckResult, CheckRun
from tlkernel.config import VisualConfig
from tlkernel.kinds import Kind
from tlkernel.looks import Methods
from tlkernel.plancheck import PlanCheck, PlanData, StageData
from tlkernel.stop import Stop
from tlkernel.wire import Open

from tlwork.plan.host import Answered
from tlwork.work.ledger import Ledger


class WorkStop(Stop):
    def __init__(self, why: str, kind: Kind, spec: AskSpec | None = None) -> None:
        super().__init__(why)
        self.why, self.kind, self.spec = why, kind, spec


class FakePlanHand:
    def __init__(self) -> None:
        self.scope = self.verify_answer = self.landed_sha = self.planner_ref = ""
        self.answered: Answered | None = None
        self.plan_data: PlanData | None = None
        self.plan_summary = self.brief_hash = ""
        self.plan_log: list[PlanStep] = []
        self.planned = self.extra = 0
        self.done: list[str] = []
        self.leftovers: list[Open] = []
        self.snap: BriefSnap | None = None


class FakeReviewHand:
    def __init__(self) -> None:
        self.scope = self.last_flag = ""
        self.plan_data: PlanData | None = None
        self.last_run: CheckRun | None = None
        self.fixes = self.at_stage = 0
        self.leftovers: list[Open] = []
        self.writer_family: str | None = "claude"


class FakeOwnerItems:
    def __init__(self) -> None:
        self.unverified: list[Open] = []
        self.unchecked: list[Open] = []


class FakeLookHand:
    Blocked = WorkStop

    def __init__(self) -> None:
        self.bead_parent, self.bead_title = "", "Add f"
        self.at_stage, self.last_flag = 0, ""
        self.writer_family: str | None = "claude"
        self.retry_after = 0.0
        self.leftovers: list[Open] = []
        self.review = FakeOwnerItems()
        self.artifact_repo, self.render_stale = "", False


class FakeBudget:
    def __init__(self) -> None:
        self.labels = ["claude", "codex"]


class FakeRepoKey:
    def __init__(self, value: str = "repo-key") -> None:
        self.value, self.calls = value, 0

    def key(self) -> str:
        self.calls += 1
        return self.value


class FakeRepoHolder:
    def __init__(self) -> None:
        self.repo = FakeRepoKey()


class FakeProbe:
    """ShellProbe needs command/file/recipe discovery; gate and testkit have no equivalent."""
    def __init__(self) -> None:
        self.commands = {"test", "echo", "true"}
        self.files: set[str] = set()
        self.dirs: set[str] = set()
        self.recipe_names: set[str] | None = None
        self.calls: list[tuple[str, str]] = []

    def has_command(self, word: str) -> bool:
        self.calls.append(("has_command", word))
        return word in self.commands

    def exists(self, path: str) -> bool:
        self.calls.append(("exists", path))
        return path in self.files or path in self.dirs

    def is_dir(self, path: str) -> bool:
        self.calls.append(("is_dir", path))
        return path in self.dirs

    def recipes(self) -> set[str] | None:
        self.calls.append(("recipes", ""))
        return None if self.recipe_names is None else set(self.recipe_names)


class FakeText:
    def __init__(self, value: str = "") -> None:
        self.value, self.exports = value, 0
        self.calls: list[tuple[object, ...]] = []

    def text(self) -> str:
        return self.value

    def export(self) -> None:
        self.exports += 1

    def shared_text(self) -> str:
        return self.value

    def rounds_text(self, last: int = 4, each: int = 600, cap: int = 2400) -> str:
        self.calls.append((last, each, cap))
        return self.value

    def add_flakes(self, new: list[Open]) -> None:
        self.calls.append(tuple(new))

    def flakes_text(self) -> str:
        return self.value

    def accepted_text(self) -> str:
        return self.value

    def so_far_text(self) -> str:
        return self.value

    def seen_lows_text(self) -> str:
        return self.value

    def note_round(self, name: str, rnd: int, kind: str, writer: str = "", open_items: Sequence[str] = ()) -> None:
        self.calls.append((name, rnd, kind, writer, tuple(open_items)))

    def note_lows(self, findings: Sequence[Open]) -> None:
        self.calls.append(tuple(findings))

    def delta(self, n: int, goal: str, files: str, anchors: str, checks: str, where: str, feedback: str, tail: str) -> str | None:
        self.calls.append((n, goal, files, anchors, checks, where, feedback, tail))
        return None


class FakeCases:
    def __init__(self) -> None:
        self.case_list: dict[str, list[str]] = {}
        self.checks: list[PlanCheck] = []
        self.rules = ""
        self.added: list[Open] = []

    def rules_text(self) -> str:
        return self.rules

    def case_checks(self) -> list[PlanCheck]:
        return list(self.checks)

    def add_cases(self, new: list[Open]) -> None:
        self.added.extend(new)

    def cases_text(self) -> str:
        return ""

    def plan_text(self, stage: int | None = None) -> str:
        return ""

    def engine_unproven(self, unchecked: list[Open], checks: list[CheckResult]) -> list[Open]:
        return list(unchecked)

    def out_of_scope(self, items: list[Open]) -> list[Open]:
        return list(items)

    def cases_of(self, cls: str) -> list[str]:
        return list(self.case_list.get(cls, []))


class FakeBriefing:
    def __init__(self) -> None:
        self.value = ""
        self.calls: list[tuple[str, tuple[object, ...], object, tuple[str, ...]]] = []

    def where(self, node: str, checks: Sequence[object] = (), failed: object = None, listed: Sequence[str] = ()) -> str:
        self.calls.append((node, tuple(checks), failed, tuple(listed)))
        return self.value


class FakeRouting:
    def __init__(self, hand: FakePlanHand) -> None:
        self.hand = hand

    def ledger(self) -> Ledger:
        return Ledger(self.hand.plan_data, self.hand.leftovers)

    def ledger_of(self, plan: PlanData) -> Ledger:
        return Ledger(plan, [])


class FakeAskFlow:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Sequence[dict[str, object]] | None, object, str]] = []

    def repo(self) -> str:
        return "repo"

    def raise_soft(self, question: str, options: Sequence[dict[str, object]] | None, cause: object, default: str) -> object:
        self.calls.append((question, options, cause, default))
        return None


class FakePictures:
    def __init__(self) -> None:
        self.config: VisualConfig | None = None
        self.methods: Methods = {}
        self.table, self.stale = "", False

    def visual_cfg(self) -> VisualConfig | None:
        return self.config

    def shot_methods(self) -> Methods:
        return self.methods

    def shot_table(self) -> str:
        return self.table

    def stage_visual(self, st: StageData) -> bool:
        return False

    def look_ready(self, st: StageData) -> bool:
        return False

    def mark_stale(self) -> None:
        self.stale = True


class FakeJudge:
    def is_look(self, u: Open) -> bool:
        return False

    def look_verify(self, gaps: Sequence[Open]) -> str:
        return ""

    def look_verdict(self, u: Open, v: str, a: Open, why: str) -> tuple[str, Open, str]:
        return v, a, why

    def look_step(self, st: StageData, w: Open, name: str, last: bool = False, *, family: str | None = None) -> str:
        return ""

    def look_review(self, st: StageData, w: Open, fix: bool = False) -> str:
        return ""

    def look_judged(self, review: Open, st: StageData, w: Open, fix: bool) -> None:
        pass

    def look_write(self, st: StageData) -> str:
        return ""


class FakeFixer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool]] = []
        self.answers: list[str] = ["accept"]

    def fix(self, kind: str, tail: str, resume: bool = False) -> str:
        self.calls.append((kind, tail, resume))
        assert self.answers, "no fix answer queued"
        return self.answers.pop(0)


class FakeWaits:
    """Work needs locked context managers; RecordedWaits only records check timings."""
    def __init__(self) -> None:
        self.calls: list[tuple[str, Path | str, str | None]] = []

    def locked(self, what: str, path: Path | str, holder: str | None = None) -> contextlib.AbstractContextManager[Path | str]:
        self.calls.append((what, path, holder))
        return contextlib.nullcontext(path)


class FakeDownscale:
    """Records an attempted conversion; empty means the caller keeps the original."""
    def __init__(self) -> None:
        self.calls: list[tuple[str | Path, str | Path, float]] = []
        self.result = ""

    def __call__(self, src: str | Path, dst: str | Path, size: float) -> str:
        self.calls.append((src, dst, size))
        return self.result


class FakeLinks:
    UNKNOWN: Literal["not checked in time"] = "not checked in time"

    def __init__(self) -> None:
        self.found: list[tuple[str, str, str]] = []
        self.answers: dict[str, tuple[bool, str]] = {}
        self.offline: set[str] = set()
        self.calls: list[str] = []

    def added_urls(self, diff: str, exts: tuple[str, ...] = (".md", ".markdown", ".txt", ".rst", ".adoc")) -> list[tuple[str, str, str]]:
        self.calls.append(diff)
        return list(self.found)

    def check(self, url: str, timeout: float = 15) -> tuple[bool, str]:
        self.calls.append(url)
        return self.answers[url]

    def check_all(self, urls: object, fn: Callable[[str], tuple[bool, str]] | None = None, workers: int = 8,
                  deadline: float = 120) -> dict[str, tuple[bool, str]]:
        assert isinstance(urls, (list, tuple))
        assert all(isinstance(url, str) for url in urls)
        return {str(url): (fn or self.check)(str(url)) for url in urls}

    def network_down(self, why: str) -> bool:
        return why in self.offline
