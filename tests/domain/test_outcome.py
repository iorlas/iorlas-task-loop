"""outcome_of: a call is done, needs the owner, or failed with delegate's predicted time."""

from taskloop.domain.lanes.outcome import Done, Failed, NeedsOwner, outcome_of
from tlkernel.delegate import DelegateResult, Retry, StopFacts

NONE = Retry(kind="none")


def stopped(permanence, retry=NONE, **kw):
    return DelegateResult(stop=StopFacts(reason="why", scope="account", permanence=permanence, retry=retry), **kw)


def test_no_stop_is_done():
    assert outcome_of(DelegateResult()) == Done()


def test_needs_owner_asks_with_the_fix_else_the_say():
    res = stopped("needs_owner", say="log in")
    assert outcome_of(res) == NeedsOwner("log in")
    fixed = DelegateResult(
        stop=StopFacts(reason="why", scope="account", permanence="needs_owner", retry=Retry(kind="none"), fix="run login")
    )
    assert outcome_of(fixed) == NeedsOwner("run login")


def test_a_transient_stop_is_failed_with_the_predicted_time():
    assert outcome_of(stopped("transient", Retry(kind="predicted", at=1234.0))) == Failed("why", 1234.0)
    assert outcome_of(stopped("transient")) == Failed("why", 0.0)
