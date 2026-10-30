"""lane_policy.decide (tl-7y6.2.6): the 20 legal stop tuples plus the unknown-tuple row, the incident rows, the network rules."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import support.paths  # noqa: E402, F401

# isort: split
from support.narrow import must, only  # noqa: E402

from taskloop.domain import outcome as oc  # noqa: E402
from taskloop.domain.lanes import policy as lp  # noqa: E402

NOW = 1_000_000.0


def stop(scope, permanence="transient", retry="none", **kw):
    return lp.Stop(scope, permanence, retry, **kw)


def ctx(**kw):
    return lp.Ctx(now=NOW, **kw)


def out(action):
    return oc.make(oc.Kind[action.kind], action.say)


def kind_of(action):
    return oc.Kind[action.kind]


class Exhaustive(unittest.TestCase):
    def test_there_are_20_legal_tuples_and_each_has_a_row_and_an_action(self):
        self.assertEqual(len(lp.LEGAL), 20)
        self.assertEqual(len(set(lp.LEGAL)), 20)
        self.assertEqual(set(lp.TABLE), set(lp.LEGAL))
        actions = (lp.Retry, lp.Wait, lp.WaitNet, lp.NewThread, lp.Reroute, lp.Yield, lp.Fail)
        for scope, perm, retry in lp.LEGAL:
            for c in (ctx(), ctx(resumed=True, attempt=2, polls=9, crashes=9, waited_net_s=9999, denied_retried=True)):
                a = lp.decide(stop(scope, perm, retry, ref="r1", resumable=True, retry_at=NOW + 60), c)
                self.assertIsInstance(a, actions, (scope, perm, retry))

    def test_the_unknown_tuple_row_pauses_the_lane_and_never_fails_or_asks(self):
        for facts in (("bead", "needs_owner", "predicted"), ("lane", "needs_owner", "poll"), ("request", "transient", "none"),
                      ("machine", "forever", "none"), ("machine", "transient", "later")):
            a = lp.decide(stop(*facts), ctx())
            self.assertIsInstance(a, lp.Yield, facts)
            self.assertEqual(kind_of(a), oc.Kind.PAUSE_LANE)

    def test_no_action_asks_the_owner_and_no_yield_is_a_fault(self):
        for scope, perm, retry in lp.LEGAL:
            a = lp.decide(
                stop(scope, perm, retry, retry_at=NOW + 9999), ctx(attempt=5, polls=5, crashes=5, waited_net_s=9999, denied_retried=True)
            )
            if isinstance(a, lp.Yield):
                self.assertIn(kind_of(a), oc.PAUSES)
            if isinstance(a, (lp.Yield, lp.Fail)):
                self.assertFalse(out(a).rule.makes_ask, (scope, perm, retry))

    def test_the_reason_is_wording_only(self):
        for scope, perm, retry in lp.LEGAL:
            a = lp.decide(stop(scope, perm, retry, reason="network"), ctx())
            b = lp.decide(stop(scope, perm, retry, reason="anything_new"), ctx())
            self.assertEqual(type(a), type(b), (scope, perm, retry))
        src = (ROOT / "src" / "taskloop" / "domain" / "lanes" / "policy.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        reads = {f.name for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)
                 for n in ast.walk(f) if isinstance(n, ast.Attribute) and n.attr == "reason"}
        self.assertEqual(reads, {"_say", "stop_of"}, "only _say (wording) and stop_of (the facts) read a reason")

    def test_the_module_is_pure(self):
        tree = ast.parse((ROOT / "src" / "taskloop" / "domain" / "lanes" / "policy.py").read_text(encoding="utf-8"))
        tops = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        tops |= {must(n.module).split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertLessEqual(tops, {"dataclasses", "typing", "taskloop", "__future__", "collections"})
        self.assertNotIn("outcome", tops)


class Network(unittest.TestCase):
    NET = ("machine", "transient", "poll")

    def test_a_network_stop_waits_for_the_net_and_resumes_the_same_ref(self):
        a = lp.decide(stop(*self.NET, ref="sess-1", partial=True), ctx(resumed=True))
        w = only(lp.WaitNet, a)
        self.assertEqual((type(a), w.resume, w.max_s), (lp.WaitNet, "sess-1", 600))
        self.assertEqual(only(lp.WaitNet, lp.decide(stop(*self.NET), ctx())).resume, "")  # no session was ever opened

    def test_a_network_stop_charges_nothing_and_never_reroutes(self):
        c = ctx(attempt=0, crashes=0, polls=0, waited_lane_s=0)
        a = lp.decide(stop(*self.NET, ref="r"), c)
        self.assertEqual(a.charges, "")
        self.assertNotIsInstance(a, (lp.Reroute, lp.NewThread, lp.Retry, lp.Fail))

    def test_past_the_cap_the_run_yields_pause_network(self):
        a = lp.decide(stop(*self.NET, ref="r"), ctx(waited_net_s=600))
        self.assertEqual((type(a), kind_of(a)), (lp.Yield, oc.Kind.PAUSE_NETWORK))
        self.assertEqual(a.charges, "")
        self.assertFalse(oc.POLICY[kind_of(a)].storm)

    def test_the_wait_shrinks_with_what_was_waited(self):
        self.assertEqual(only(lp.WaitNet, lp.decide(stop(*self.NET), ctx(waited_net_s=450))).max_s, 150)

    def test_a_probe_that_says_up_at_three_stops_pauses_with_a_banner_and_a_doubling_backoff(self):
        a = lp.decide(stop(*self.NET), ctx(net_up_stops=3))
        p = only(lp.Yield, a)
        self.assertEqual((kind_of(a), p.banner, p.retry_after), (oc.Kind.PAUSE_NETWORK, True, NOW + 1800))
        self.assertEqual(only(lp.Yield, lp.decide(stop(*self.NET), ctx(net_up_stops=5))).retry_after, NOW + 7200)
        self.assertEqual(only(lp.Yield, lp.decide(stop(*self.NET), ctx(net_up_stops=40))).retry_after, NOW + 21600)
        self.assertEqual(type(lp.decide(stop(*self.NET), ctx(net_up_stops=2))), lp.WaitNet)


class Incidents(unittest.TestCase):
    def test_logged_out_twice_pauses_the_lane_with_the_login_fix_and_no_ask(self):
        for _ in range(2):
            a = lp.decide(stop("lane", "needs_owner", "none", reason="logged_out", fix="claude /login", lane="CLAUDE"), ctx())
            self.assertEqual((kind_of(a), only(lp.Yield, a).fix, out(a).rule.makes_ask), (oc.Kind.PAUSE_LANE, "claude /login", False))

    def test_exit_15_is_a_kill_pause_never_a_fail_or_an_ask(self):
        for facts in (("machine", "transient", "none"), ("machine", "needs_owner", "none"), ("machine", "transient", "poll")):
            a = lp.decide(stop(*facts, signal=15, reason="killed"), ctx(crashes=9, waited_net_s=9999))
            self.assertEqual(kind_of(a), oc.Kind.PAUSE_KILLED, facts)

    def test_busy_polls_three_times_then_moves_on(self):
        s = stop("lane", "transient", "poll", lane="OPENAI", retry_at=NOW + 20)
        a = lp.decide(s, ctx(polls=2))
        w = only(lp.Wait, a)
        self.assertEqual((type(a), w.until, w.charges), (lp.Wait, NOW + 20, "polls"))
        self.assertEqual(lp.decide(s, ctx(polls=3)), lp.Reroute("OPENAI"))
        self.assertEqual(lp.decide(s, ctx(polls=3, resumed=True)), lp.NewThread("lane_out"))

    def test_busy_with_resume_keeps_the_thread_while_polling(self):
        a = lp.decide(stop("lane", "transient", "poll", ref="r9", resumable=True), ctx(polls=0, resumed=True))
        self.assertEqual((type(a), only(lp.Wait, a).resume), (lp.Wait, "r9"))

    def test_a_rate_limit_inside_the_cap_waits_and_beyond_it_pauses_with_the_time(self):
        s = stop("lane", "transient", "predicted", retry_at=NOW + 120)
        self.assertEqual(lp.decide(s, ctx()), lp.Wait(NOW + 120))
        far = lp.decide(stop("lane", "transient", "predicted", retry_at=NOW + 5000), ctx())
        self.assertEqual((kind_of(far), only(lp.Yield, far).retry_after), (oc.Kind.PAUSE_LANE, NOW + 5000))
        self.assertEqual(lp.decide(s, ctx(resumed=True)), lp.NewThread("lane_out"))

    def test_the_wait_cap_is_shared_across_a_steps_waits(self):
        s = stop("lane", "transient", "predicted", retry_at=NOW + 100)
        self.assertEqual(kind_of(lp.decide(s, ctx(waited_lane_s=100))), oc.Kind.PAUSE_LANE)

    def test_spending_limit_pauses_the_lane_and_does_not_ask(self):
        a = lp.decide(stop("lane", "needs_owner", "none", reason="credit_exhausted"), ctx())
        self.assertEqual((kind_of(a), out(a).rule.makes_ask), (oc.Kind.PAUSE_LANE, False))

    def test_bad_request_is_a_fault_with_no_ask(self):
        a = lp.decide(stop("caller", "needs_owner", "none", reason="bad_request"), ctx())
        self.assertEqual((type(a), kind_of(a), out(a).rule.makes_ask), (lp.Fail, oc.Kind.FAULT_BAD_REQUEST, False))
        self.assertTrue(out(a).fingerprint.startswith("FAULT_BAD_REQUEST"))

    def test_hung_reroutes_away_from_the_model_then_pauses(self):
        s = stop("model", "transient", "none", model="grok-4", lane="GROK")
        self.assertEqual(lp.decide(s, ctx()), lp.Reroute("grok-4"))
        self.assertEqual(lp.decide(stop("lane", "transient", "none", lane="GROK"), ctx()), lp.Reroute("GROK"))
        self.assertEqual(kind_of(lp.decide(s, ctx(attempt=2))), oc.Kind.PAUSE_LANE)

    def test_secrets_get_one_apply_patch_thread_then_a_fault(self):
        s = stop("bead", "needs_owner", "none", reason="secrets")
        self.assertEqual(lp.decide(s, ctx(secret_fp=True)), lp.NewThread("apply_patch", "denied_retried", "denied_secret"))
        for c in (ctx(secret_fp=True, denied_retried=True), ctx()):  # a second denial, and a real secret path, are faults
            a = lp.decide(s, c)
            self.assertEqual((type(a), kind_of(a)), (lp.Fail, oc.Kind.FAULT_DENIED))

    def test_a_failed_worker_is_tried_once_more_resumed_when_it_can_be(self):
        self.assertEqual(lp.decide(stop("bead", resumable=True, ref="r"), ctx()), lp.Retry(NOW, "r", "attempt", "worker_failed"))
        self.assertEqual(lp.decide(stop("bead"), ctx()), lp.NewThread("", "attempt", "worker_failed"))
        self.assertEqual(kind_of(lp.decide(stop("bead"), ctx(attempt=1))), oc.Kind.FAULT_INFRA)

    def test_a_delegate_crash_rests_then_retries_fresh_then_is_a_fault(self):
        s = stop("machine", "transient", "none")
        self.assertEqual(lp.decide(s, ctx()), lp.Retry(NOW + 30, "", "crashes", "crash"))
        self.assertEqual(lp.decide(s, ctx(crashes=1)), lp.Retry(NOW + 120, "", "crashes", "crash"))
        self.assertEqual(kind_of(lp.decide(s, ctx(crashes=2))), oc.Kind.FAULT_CRASHED)

    def test_no_lane_and_setup_pause_the_lane(self):
        self.assertEqual(kind_of(lp.decide(stop("machine", "transient", "predicted", retry_at=NOW + 900), ctx())), oc.Kind.PAUSE_LANE)
        self.assertEqual(kind_of(lp.decide(stop("machine", "needs_owner", "none", fix="tl doctor"), ctx())), oc.Kind.PAUSE_LANE)

    def test_duplicate_task_polls_then_pauses(self):
        s = stop("bead", "transient", "poll")
        self.assertEqual(type(lp.decide(s, ctx(polls=2))), lp.Wait)
        self.assertEqual(kind_of(lp.decide(s, ctx(polls=3))), oc.Kind.PAUSE_LANE)


if __name__ == "__main__":
    unittest.main()
