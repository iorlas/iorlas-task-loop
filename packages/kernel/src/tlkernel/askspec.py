"""What a raise site knows about an ask, before it has an id, a time or a file: the class, the decision, what was tried, the options."""
from dataclasses import dataclass, field

from tlkernel.ask import AskDetail, AskOption
from tlkernel.askenums import AskClass, AskKind
from tlkernel.asklint import KIND_OF
from tlkernel.dash import OwnerCause


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
        kind = KIND_OF[self.ask_class]
        if kind is None:
            raise ValueError(f"class: {self.ask_class.value} is the engine's own trouble, never an ask")
        return kind
