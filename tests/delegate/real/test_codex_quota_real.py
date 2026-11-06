"""Codex quota read (delegate-av1) and Claude-last routing (delegate-m86), with responses recorded from `codex app-server` on 2026-10-26."""

import copy
import os
from typing import Any

from delegate.app import env, usage
from delegate.contracts.state import UsageCache
from delegate.domain.lanes.lane import Lane
from support.procsim import real_proc
from support.tmpdir import TemporaryDirectory

import hermetic  # noqa: F401  (a home of its own for every test)
import routing_support as support
from test_route import CFG, T, lanes

# `account/rateLimits/read` as recorded: Pro Lite, one weekly window sent as `primary`, no `secondary`, no other bucket, no credits.
RECORDED: dict[str, Any] = {
    "ordinaryUsageAllowed": True,
    "rateLimits": {
        "limitId": "codex",
        "limitName": None,
        "normalModelSlug": None,
        "primary": {"usedPercent": 6, "windowDurationMins": 10080, "resetsAt": 1793544194},
        "secondary": None,
        "credits": {"hasCredits": False, "unlimited": False, "balance": "0"},
        "individualLimit": None,
        "spendControlReached": False,
        "planType": "prolite",
        "rateLimitReachedType": None,
    },
    "rateLimitsByLimitId": {
        "codex": {
            "limitId": "codex",
            "limitName": None,
            "primary": {"usedPercent": 6, "windowDurationMins": 10080, "resetsAt": 1793544194},
            "secondary": None,
            "spendControlReached": False,
            "planType": "prolite",
            "rateLimitReachedType": None,
        }
    },
    "rateLimitResetCredits": {"availableCount": 0, "credits": []},
}

# The same account's last rollout event of the old window (2026-10-25T02:31Z, "plus"-style 7-day window due Fri 30 Oct 19:42 EET)
# and the first of the new one.
OLD = {"usedPercent": 84, "windowDurationMins": 10080, "resetsAt": 1793382120}
NEW_RESET = 1793544194
NOW = 1793000000  # 2026-10-26, before both resets


def with_res(res, S=None, st=None, t=NOW):
    lane = Lane("OPENAI_SUBSCRIPTION", "openai", "subscription")
    env.update_state(lambda s_: setattr(s_, "codex_limits", UsageCache(at=t, data=res)))
    S = env.settings_of(CFG) if S is None else env.settings_of({**CFG, "settings": S})
    usage.read_codex(lane, S, st if st is not None else env.load_state(), t)
    return lane


class Fresh:
    def setup_method(self):
        self.saved = os.environ.get("DELEGATE_CONFIG_DIR")
        self.tmp = TemporaryDirectory()
        os.environ["DELEGATE_CONFIG_DIR"] = self.tmp.name

    def teardown_method(self):
        if self.saved is None:
            os.environ.pop("DELEGATE_CONFIG_DIR", None)
        else:
            os.environ["DELEGATE_CONFIG_DIR"] = self.saved
        self.tmp.cleanup()




class ClaudeLast(Fresh):
    def grok(self, **over):
        g = Lane("GROK_SUBSCRIPTION", "xai", "subscription")
        for k, v in over.items():
            setattr(g, k, v)
        return g

    def everything(self, **over):
        ls = lanes()
        ls["GROK_SUBSCRIPTION"] = self.grok()
        for fam, name in (("deepseek", "DEEPSEEK_FREE"), ("zai", "ZAI_CODING_SUBSCRIPTION")):
            ls[name] = Lane(name, fam, "subscription")
        return ls

    def cfg(self):
        c = copy.deepcopy(CFG)
        return c

    def pick(self, role, ls, **args):
        a = {"authored_by": None, "failed": [], "premium": None, "allow_degraded": False}
        a.update(args)
        return support.decide(role, self.cfg(), ls, {}, T, a)

    @real_proc("delegate: a worker, git or CLI process")
    def test_all_lanes_up_a_non_claude_lane_is_picked_for_every_role(self):
        for role in CFG["roles"]:
            for who in [None] if role != "reviewer" else [None, "openai", "claude", "xai", "deepseek", "zai"]:
                d = self.pick(role, self.everything(), authored_by=who)
                assert d["action"] == "run", (role, who)
                assert "CLAUDE" not in d["lane"], (role, who, d["lane"])



    @real_proc("delegate: a worker, git or CLI process")
    def test_a_relaxed_non_claude_lane_beats_a_strict_claude_lane(self):
        ls = self.everything()
        for n in ("GROK_SUBSCRIPTION", "DEEPSEEK_FREE", "ZAI_CODING_SUBSCRIPTION"):
            ls[n].out, ls[n].out_until = True, T + 3600
        ls["OPENAI_SUBSCRIPTION"].week = 96  # over the strict gate (95), under the ceiling (98)
        d = self.pick("worker", ls)
        assert (d["lane"], d["pass"]) == ("OPENAI_SUBSCRIPTION", "relaxed")

    @real_proc("delegate: a worker, git or CLI process")
    def test_same_family_review_by_a_non_claude_lane_still_precedes_claude(self):
        ls = self.everything()
        for n in ("GROK_SUBSCRIPTION", "DEEPSEEK_FREE", "ZAI_CODING_SUBSCRIPTION"):
            ls[n].out, ls[n].out_until = True, T + 3600
        d = self.pick("reviewer", ls, authored_by="openai")
        assert (d["lane"], d["flag"]) == ("OPENAI_SUBSCRIPTION", "same_family")
