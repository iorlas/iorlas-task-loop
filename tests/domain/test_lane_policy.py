"""lane_policy.decide (tl-7y6.2.6): the 20 legal stop tuples plus the unknown-tuple row, the incident rows, the network rules."""
import ast
from pathlib import Path

from tltestkit.case import Case

ROOT = Path(__file__).resolve().parents[2]

# isort: split
from taskloop.domain.lanes import policy as lp  # noqa: E402
from taskloop.domain.lanes.says import stop_why  # noqa: E402
from tlkernel import runoutcome as oc  # noqa: E402
from tlkernel.kinds import PAUSES, Kind  # noqa: E402
from tltestkit.narrow import must, only  # noqa: E402

NOW = 1_000_000.0


def stop(scope, permanence="transient", retry="none", **kw):
    return lp.Stop(scope, permanence, retry, **kw)


def ctx(**kw):
    return lp.Ctx(**kw)


def out(action):
    return oc.make(Kind[action.kind])


def kind_of(action):
    return Kind[action.kind]


class Exhaustive(Case):
    def test_there_are_20_legal_tuples_and_each_has_a_row_and_an_action(self):
        assert len(lp.LEGAL) == 20
        assert len(set(lp.LEGAL)) == 20
        assert set(lp.TABLE) == set(lp.LEGAL)
        actions = (lp.NewThread, lp.Reroute, lp.Yield, lp.Fail)
        for scope, perm, retry in lp.LEGAL:
            for c in (ctx(), ctx(attempt=2, denied_retried=True)):
                a = lp.decide(stop(scope, perm, retry, retry_at=NOW + 60), c)
                assert isinstance(a, actions), (scope, perm, retry)

    def test_the_unknown_tuple_row_pauses_the_lane_and_never_fails_or_asks(self):
        for facts in (("bead", "needs_owner", "predicted"), ("account", "needs_owner", "poll"), ("request", "transient", "none"),
                      ("machine", "forever", "none"), ("machine", "transient", "later")):
            a = lp.decide(stop(*facts), ctx())
            assert isinstance(a, lp.Yield), facts
            assert kind_of(a) == Kind.PAUSE_LANE

    def test_no_action_asks_the_owner_and_no_yield_is_a_fault(self):
        for scope, perm, retry in lp.LEGAL:
            a = lp.decide(
                stop(scope, perm, retry, retry_at=NOW + 9999), ctx(attempt=5, denied_retried=True)
            )
            if isinstance(a, lp.Yield):
                assert kind_of(a) in PAUSES
            if isinstance(a, (lp.Yield, lp.Fail)):
                assert not out(a).rule.makes_ask, (scope, perm, retry)

    def test_the_reason_is_wording_only(self):
        for scope, perm, retry in lp.LEGAL:
            a = lp.decide(stop(scope, perm, retry, reason="network"), ctx())
            b = lp.decide(stop(scope, perm, retry, reason="anything_new"), ctx())
            assert type(a) is type(b), (scope, perm, retry)
        src = (ROOT / "src" / "taskloop" / "domain" / "lanes" / "policy.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        reads = {f.name for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)
                 for n in ast.walk(f) if isinstance(n, ast.Attribute) and n.attr == "reason"}
        assert reads == {"stop_of"}, "only stop_of reads a reason to extract stop facts"

    def test_the_module_is_pure(self):
        tree = ast.parse((ROOT / "src" / "taskloop" / "domain" / "lanes" / "policy.py").read_text(encoding="utf-8"))
        tops = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        tops |= {must(n.module).split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert tops <= {"dataclasses", "typing", "taskloop", "tlkernel", "__future__", "collections"}
        assert "outcome" not in tops


def test_network_stop_pauses_immediately():
    action = lp.decide(stop("machine", "transient", "poll"), ctx())
    assert isinstance(action, lp.Yield)
    assert (action.kind, action.retry_after) == ("PAUSE_NETWORK", 0)


class Incidents(Case):
    def test_logged_out_twice_pauses_the_lane_with_the_login_fix_and_no_ask(self):
        for _ in range(2):
            s = stop("account", "needs_owner", "none", reason="logged_out", fix="claude /login", lane="CLAUDE")
            a = only(lp.Yield, lp.decide(s, ctx()))
            assert (kind_of(a), out(a).rule.makes_ask) == (Kind.PAUSE_LANE, False)
            assert "claude /login" in stop_why("write", a.kind, s, "", now=NOW)

    def test_exit_15_is_a_kill_pause_never_a_fail_or_an_ask(self):
        for facts in (("machine", "transient", "none"), ("machine", "needs_owner", "none"), ("machine", "transient", "poll")):
            a = lp.decide(stop(*facts, signal=15, reason="killed"), ctx())
            assert kind_of(a) == Kind.PAUSE_KILLED, facts


    def test_spending_limit_pauses_the_lane_and_does_not_ask(self):
        a = lp.decide(stop("account", "needs_owner", "none", reason="credit_exhausted"), ctx())
        assert (kind_of(a), out(a).rule.makes_ask) == (Kind.PAUSE_LANE, False)

    def test_bad_request_is_a_fault_with_no_ask(self):
        a = lp.decide(stop("caller", "needs_owner", "none", reason="bad_request"), ctx())
        assert (type(a), kind_of(a), out(a).rule.makes_ask) == (lp.Fail, Kind.FAULT_BAD_REQUEST, False)
        assert out(a).fingerprint.startswith("FAULT_BAD_REQUEST")

    def test_hung_reroutes_away_from_the_model_then_pauses(self):
        s = stop("model", "transient", "none", model="grok-4", lane="GROK")
        assert lp.decide(s, ctx()) == lp.Reroute("grok-4")
        assert lp.decide(stop("account", "transient", "none", lane="GROK"), ctx()) == lp.Reroute("GROK")
        assert kind_of(lp.decide(s, ctx(attempt=2))) == Kind.PAUSE_LANE

    def test_secrets_get_one_apply_patch_thread_then_a_fault(self):
        s = stop("bead", "needs_owner", "none", reason="secrets")
        assert lp.decide(s, ctx(secret_fp=True)) == lp.NewThread("apply_patch", "denied_retried", "denied_secret")
        for c in (ctx(secret_fp=True, denied_retried=True), ctx()):  # a second denial, and a real secret path, are faults
            a = lp.decide(s, c)
            assert (type(a), kind_of(a)) == (lp.Fail, Kind.FAULT_DENIED)

    def test_no_lane_and_setup_pause_the_lane(self):
        assert kind_of(lp.decide(stop("machine", "transient", "predicted", retry_at=NOW + 900), ctx())) == Kind.PAUSE_LANE
        assert kind_of(lp.decide(stop("machine", "needs_owner", "none", fix="tl doctor"), ctx())) == Kind.PAUSE_LANE


def test_lane_poll_moves_on_and_bead_poll_pauses():
    s = stop("account", "transient", "poll", lane="OPENAI")
    assert lp.decide(s, ctx()) == lp.Reroute("OPENAI")
    assert lp.decide(s, ctx()) == lp.Reroute("OPENAI")
    assert kind_of(lp.decide(stop("bead", "transient", "poll"), ctx())) == Kind.PAUSE_LANE


def test_predicted_lane_always_parks():
    for gap in (120, 5000):
        s = stop("account", "transient", "predicted", retry_at=NOW + gap)
        a = only(lp.Yield, lp.decide(s, ctx()))
        assert (a.kind, a.retry_after) == ("PAUSE_LANE", NOW + gap)
        assert lp.decide(s, ctx()) == lp.Yield("PAUSE_LANE", NOW + gap)


def test_failed_worker_faults_after_delegate_recovery():
    s = stop("bead")
    assert kind_of(lp.decide(s, ctx())) == Kind.FAULT_INFRA
    assert lp.decide(s, ctx()) == lp.Fail("FAULT_INFRA", "worker_failed")
    assert kind_of(lp.decide(s, ctx(attempt=1))) == Kind.FAULT_INFRA


def test_delegate_crash_fails_immediately():
    assert lp.decide(stop("machine"), ctx()) == lp.Fail("FAULT_CRASHED")


def test_hurt_write_asks_after_delegate_recovery():
    s = stop("bead", exit_code=-15, lane="lane", model="model")
    assert lp.decide(s, ctx(node="write")) == lp.Fail("ASK_STUCK", "worker_failed")
    assert kind_of(lp.decide(s, ctx(node="write"))) == Kind.ASK_STUCK
    assert kind_of(lp.decide(s, ctx(node="write", attempt=1))) == Kind.ASK_STUCK
