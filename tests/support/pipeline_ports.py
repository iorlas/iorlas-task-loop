"""Recording structural fakes for the pipeline close capabilities."""
from collections.abc import Callable

from taskloop.contracts import fence
from taskloop.contracts.bead import Bead
from taskloop.contracts.delegate import Permanence
from taskloop.contracts.enums import Outcome
from taskloop.contracts.gitport import Git
from taskloop.contracts.kinds import Kind
from taskloop.contracts.parks import Park
from taskloop.domain.asks.spec import AskSpec
from taskloop.domain.lanes.pause_reasons import Producer


class FakeAskRules:
    def __init__(self, result: list[str] | None = None) -> None:
        self.calls: list[AskSpec] = []
        self.result = result if result is not None else []

    def problems(self, spec: AskSpec) -> list[str]:
        self.calls.append(spec)
        return self.result


class FakeParkBook:
    def __init__(self, result: Park | None = None) -> None:
        self.paused_calls: list[tuple[Bead, Kind, str, float, str, float, str, Producer | None, Permanence | None]] = []
        self.ended_calls: list[tuple[Bead, Kind, str, float]] = []
        self.result = result

    def paused(self, bead: Bead, kind: Kind, run: str, now: float, *, reason: str = "",
               not_before: float = 0.0, fingerprint: str = "", producer: Producer | None = None,
               permanence: Permanence | None = None) -> Park | None:
        self.paused_calls.append((bead, kind, run, now, reason, not_before, fingerprint, producer, permanence))
        return self.result

    def ended(self, bead: Bead, kind: Kind, run: str, now: float) -> None:
        self.ended_calls.append((bead, kind, run, now))


class FakeFollowUps:
    def __init__(self, result: list[dict[str, str]] | None = None) -> None:
        self.calls: list[tuple[()]] = []
        self.result = result if result is not None else []

    def file(self) -> list[dict[str, str]]:
        self.calls.append(())
        return self.result


class FakeLandCleanup:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def retry(self, repo: str) -> None:
        self.calls.append(repo)


class FakeBeadClosing:
    def __init__(self, close_result: int = 0, block_result: int = 0) -> None:
        self.close_calls: list[tuple[fence.Claim, str | None]] = []
        self.block_calls: list[tuple[fence.Claim, str, Callable[[str], None] | None]] = []
        self.close_result, self.block_result = close_result, block_result

    def close(self, claim: fence.Claim, reason: str | None) -> int:
        self.close_calls.append((claim, reason))
        return self.close_result

    def block(self, claim: fence.Claim, why: str, say: Callable[[str], None] | None = None) -> int:
        self.block_calls.append((claim, why, say))
        return self.block_result


class FakeSlotting:
    def __init__(self) -> None:
        self.calls: list[tuple[Outcome, str]] = []

    def leave_slot(self, outcome: Outcome, branch: str) -> None:
        self.calls.append((outcome, branch))


class FakeNarrate:
    def __init__(self) -> None:
        self.notes: list[str] = []
        self.warnings: list[str] = []

    def note(self, text: str) -> int:
        self.notes.append(text)
        return len(self.notes)

    def warn(self, text: str) -> int:
        self.warnings.append(text)
        return len(self.warnings)


class FakeTrustRefusal:
    def __init__(self, reason: str = "") -> None:
        self.reason = reason
        self.calls: list[tuple[Git, str, str, Bead | None]] = []

    def refusal(self, git: Git, wt: str, base: str, bead: Bead | None) -> str:
        self.calls.append((git, wt, base, bead))
        return self.reason
