"""The terminal outcome of one worker call, the only thing the engine will need of a stop once delegate owns retries
(docs/design/isolation.md, B2): done, needs the owner, or failed with a time to try again. A pure reading of the answer's own facts;
nothing here decides what to do next (that is `policy.decide` until B2b removes it)."""
from dataclasses import dataclass

from tlkernel.delegate import DelegateResult


@dataclass(frozen=True)
class Done:
    pass


@dataclass(frozen=True)
class NeedsOwner:
    question: str


@dataclass(frozen=True)
class Failed:
    reason: str
    retry_after: float = 0.0  # epoch seconds delegate predicts the cause heals (0: no prediction)


Outcome = Done | NeedsOwner | Failed


def outcome_of(res: DelegateResult) -> Outcome:
    """A call that did not stop is Done; a stop whose permanence is needs_owner asks the owner (its fix, else its say); any other stop is
    Failed with delegate's predicted time (`retry.at`) when it gave one."""
    st = res.stop
    if st is None:
        return Done()
    if st.permanence == "needs_owner":
        return NeedsOwner(st.fix or res.say or st.reason)
    return Failed(st.reason, float(st.retry.at or 0.0))
