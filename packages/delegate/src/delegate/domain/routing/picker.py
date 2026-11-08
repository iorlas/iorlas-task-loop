"""AccountPicker: which account of one family serves a model right now (the first usable one)."""

from delegate.contracts.routing import Settings
from delegate.contracts.state import Hold
from delegate.domain.accounts.account import Account


class AccountPicker:
    def __init__(self, settings: Settings, holds: dict[str, Hold | None], t: float) -> None:
        self.s = settings
        self.holds = holds  # account name -> the hold covering the role being decided
        self.t = t

    def usable(self, account: Account, relaxed: bool, model: str | None = None) -> tuple[bool, str]:
        return account.usable(self.s, relaxed, model, self.holds.get(account.name))

    def pick(self, family: str, accounts: dict[str, Account], relaxed: bool, trace: list[str], model: str | None = None) -> Account | None:
        """The account of `family` to use now for `model`, or None. Appends the reasoning to `trace`."""
        ok = []
        for account in (x for x in accounts.values() if x.family == family):
            good, why = self.usable(account, relaxed, model)
            trace.append(f"{account.name}: {'usable' if good else 'rejected, ' + why}")
            if good:
                ok.append(account)
        if not ok:
            return None
        return ok[0]
