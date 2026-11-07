"""PUSHSLOW (tl-bxk.10.33.1): the land push has its own time limit, a timed-out push rests and is tried again, and a slow push says
where its time went."""

from support.fakegit import FakeGit
from support.narrow_land import table_kit

from taskloop.app.land import push
from taskloop.app.land.gate import mint
from taskloop.app.land.host import Land, Next, Phase
from tlkernel.ids import TreeSha
from tlkernel.landmatchers import Push as PushText
from tlkernel.runkey import BaseSha
from tltestkit.case import Case

TIMED_OUT = (124, "\n(timed out after 10 min: the engine stopped it and everything it started)")


def kit(pushes, up=True):
    git = FakeGit(**{"rev_parse__origin/main": ["a"], "rev_parse__HEAD": ["pushed"], "rev_parse__HEAD^{tree}": "tree",
                     "push": list(pushes)})
    return table_kit(git, up=up)


def push_once(host):
    return host.pusher.push(Land(), mint(TreeSha("tree"), BaseSha("a")))


class PushSlow(Case):
    def test_the_land_command_runs_with_the_push_limit_not_the_default_hour(self):
        host = kit([(0, "")])
        seen = []
        real = host.pushing.sh
        host.pushing.sh = lambda cmd, **kw: (seen.append(kw.get("timeout")), real(cmd, **kw))[1]
        assert push_once(host) == "pushed"
        assert seen == [push.PUSH_TIMEOUT_S]
        assert push.PUSH_TIMEOUT_S < 3600

    def test_a_push_that_timed_out_is_a_network_error_the_land_rests_and_tries_again(self):
        assert PushText.transient(TIMED_OUT[1])
        host = kit([TIMED_OUT], up=False)
        st = Land()
        assert host.pusher.push(st, mint(TreeSha("tree"), BaseSha("a"))) is Next.REST
        assert st.phase is Phase.NET_DOWN

    def test_a_slow_push_logs_where_the_time_went_and_what_ended_it(self):
        ticks = iter([0.0, 40.0, 100.0])  # lfs 40 s, land command 60 s
        host = kit([(0, "")])
        host.pusher.clock = lambda: next(ticks)
        assert push_once(host) == "pushed"
        (line,) = [w for w in host.pushing.warnings if w.startswith("slow push")]
        assert "lfs 40s" in line and "land command 60s" in line and "pushed" in line

    def test_a_fast_push_logs_nothing(self):
        ticks = iter([0.0, 1.0, 3.0])
        host = kit([(0, "")])
        host.pusher.clock = lambda: next(ticks)
        assert push_once(host) == "pushed"
        assert not [w for w in host.pushing.warnings if w.startswith("slow push")]
