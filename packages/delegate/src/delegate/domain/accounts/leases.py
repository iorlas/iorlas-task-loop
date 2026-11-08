"""LeaseBook: the runs in flight (state.json `leases`). A running `run` holds a lease, renewed while it lives; one that expires is
dropped."""

from delegate.contracts.state import Lease

LEASE_TTL, LEASE_RENEW = 120, 30  # a lease expires by itself if route.py is killed


def suspect(lease: Lease, t: float) -> bool:
    """A lease whose worker printed nothing for longer than its CLI's silence limit: it is probably hung and does not count against the
    account's cap (the 22 false `busy` of 25 Oct). Its own watchdog stops the worker; this only stops it blocking the account meanwhile."""
    return bool(lease.silence_s) and t - max(lease.last_event or 0, lease.start or 0) > lease.silence_s


class LeaseBook:
    def __init__(self, leases: dict[str, Lease]) -> None:
        self.leases = leases

    def live(self, t: float) -> dict[str, Lease]:
        return {k: v for k, v in self.leases.items() if v.expires > t}

    def counts(self, account: str, t: float) -> dict[str, int]:
        """-> {live, suspect}: the running leases on `account` (suspect ones are also in live)."""
        mine = [v for v in self.live(t).values() if v.account == account]
        return {"live": len(mine), "suspect": sum(1 for v in mine if suspect(v, t))}

    def running(self, account: str, t: float) -> int:
        """Leases on `account` that count against its cap."""
        return sum(1 for v in self.live(t).values() if v.account == account and not suspect(v, t))
