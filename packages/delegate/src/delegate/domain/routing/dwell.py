"""DwellMemory: the account last chosen per family (state.json `prev`), so a choice between two accounts of one family does not flap."""

from delegate.contracts.state import Dwell


class DwellMemory:
    def __init__(self, prev: dict[str, Dwell], minutes: float) -> None:
        self.prev = prev
        self.minutes = minutes

    def last(self, family: str) -> str | None:
        d = self.prev.get(family)
        return d.account if d else None

    def note(self, family: str, account: str, t: float) -> Dwell | None:
        """The record to store when the choice changed, else None."""
        d = self.prev.get(family)
        return None if d and d.account == account else Dwell(account=account, since=t)
