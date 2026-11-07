"""One pass of a run: the spans between two loop turns, its end and its resume note."""
from dataclasses import dataclass

from taskloop_dash.views.runfacts import Run, Span
from tlkernel.dash import PassEnd, Resumed
from tlkernel.runlife import Liveness


@dataclass(frozen=True)
class PassView:
    n: int
    run: Run
    spans: tuple[Span, ...]
    end: PassEnd
    text: str
    resumed: Resumed | None
    detail: str = ""

    @property
    def t0(self) -> float:
        return self.spans[0].t0

    @property
    def t1(self) -> float:
        return self.run.end_of(self.spans[-1])

    @property
    def live(self) -> bool:
        """The run still writes and this is its last pass."""
        return self.run.life is Liveness.LIVE and self.end == "" and self.spans[-1].t1 is None
