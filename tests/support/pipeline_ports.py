"""Recording structural fakes for the pipeline close capabilities."""
from collections.abc import Callable, Sequence

from tlkernel import fence
from tlkernel.askspec import AskSpec
from tlkernel.bead import Bead
from tlkernel.checkpoint import Checkpoint
from tlkernel.delegate import Permanence
from tlkernel.enums import Outcome, Step
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.parks import Park
from tlkernel.pausereasons import Producer
from tlkernel.review import ReviewState
from tlkernel.run import NetPause, ReexecNote


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
               permanence: Permanence | None = None) -> Park:
        self.paused_calls.append((bead, kind, run, now, reason, not_before, fingerprint, producer, permanence))
        return self.result if self.result is not None else Park(
            bead=bead.id, hash="hash", runs=1, run=run, t=now, reason=reason or kind.value,
            permanence=permanence or "transient", retry_at=not_before)

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


class FakeHeadHistory:
    def __init__(self, result: str = "") -> None:
        self.result = result
        self.calls: list[tuple[str, str, int]] = []

    def ahead_of(self, wt: str, base: str, n: int) -> str:
        self.calls.append((wt, base, n))
        return self.result

    def since(self, wt: str, head: str, n: int) -> str:
        self.calls.append((wt, head, n))
        return self.result


class FakeReviewRestore:
    def __init__(self) -> None:
        self.calls: list[tuple[ReviewState, bool, bool]] = []

    def apply(self, review: ReviewState, *, unchecked: bool, late: bool = False) -> None:
        self.calls.append((review, unchecked, late))


class FakeReexecs:
    def __init__(self) -> None:
        self.pauses: list[NetPause] = []
        self.notes: list[ReexecNote] = []
        self.dropped: list[BeadId] = []
        self.execs: list[tuple[list[str], dict[str, str]]] = []
        self.argv: list[str] | None = ["run-task"]
        self.error: OSError | None = None

    def net_pause(self, pause: NetPause) -> None:
        if self.error:
            raise self.error
        self.pauses.append(pause)

    def note(self, note: ReexecNote) -> None:
        self.notes.append(note)

    def args(self, argv: Sequence[str], slot: str, wt: str) -> list[str] | None:
        return self.argv

    def drop(self, bead: BeadId) -> None:
        self.dropped.append(bead)

    def exec(self, argv: list[str], env: dict[str, str]) -> None:
        self.execs.append((argv, env))
        if self.error:
            raise self.error


class FakeTrail:
    def __init__(self) -> None:
        self.events: list[tuple[Identity, str, str, dict[str, str]]] = []

    def event(self, by: Identity, kind: str, bead: str, **fields: str) -> None:
        self.events.append((by, kind, bead, fields))


class FakeRoundSteps:
    def __init__(self, following: Step = Step.VERIFY) -> None:
        self.following = following
        self.calls: list[tuple[Step, Checkpoint | None]] = []

    def round_step(self, step: Step, ck: Checkpoint | None) -> Step:
        self.calls.append((step, ck))
        return self.following
