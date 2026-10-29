"""What a raise site knows about an ask, before it has an id, a time or a file: the class, the decision, what was tried, the options."""
from dataclasses import dataclass, field

from taskloop.contracts.ask import AskDetail, AskOption
from taskloop.contracts.dash import OwnerCause
from taskloop.contracts.enums import AskClass, AskKind
from taskloop.domain.asks.lint import KIND_OF


@dataclass(frozen=True)
class AskSpec:
    ask_class: AskClass
    decision: str
    tried: list[str] = field(default_factory=list)
    options: list[AskOption] = field(default_factory=list)
    detail: AskDetail = field(default_factory=AskDetail)
    owner_cause: OwnerCause = OwnerCause.UNKNOWN  # what the agent declared; the engine's own stops declare none
    blocking: bool = True  # False: a soft ask, the run goes on with `default`
    default: str = ""

    @property
    def kind(self) -> AskKind:
        return KIND_OF[self.ask_class]
