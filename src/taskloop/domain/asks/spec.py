"""What a raise site knows about an ask, before it has an id, a time or a file: the class, the decision, what was tried, the options."""
from dataclasses import dataclass, field

from taskloop.contracts.ask import AskDetail, AskOption
from taskloop.contracts.enums import AskClass, AskKind
from taskloop.domain.asks.lint import KIND_OF


@dataclass(frozen=True)
class AskSpec:
    ask_class: AskClass
    decision: str
    tried: list[str] = field(default_factory=list)
    options: list[AskOption] = field(default_factory=list)
    detail: AskDetail = field(default_factory=AskDetail)

    @property
    def kind(self) -> AskKind:
        return KIND_OF[self.ask_class]
