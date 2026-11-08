"""Settler: the one place a classified outcome (the shelf any_agent.classify) is applied to the answer and, for an account-scoped reason, to
the account's state. All three launchers end here. `apply` is the only entry; one method per reason, found by name.

`reset` is the default end of a limit when the message names no time; `login` the hint stored
with a logged-out account and the text of the answer with {why}.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass

from any_agent import reset_parse
from any_agent.classify import Outcome, classify, with_network

from delegate.app import answer
from delegate.app.env import Args
from delegate.contracts.json_types import Json, as_str
from delegate.contracts.state import OutState
from delegate.contracts.stores import StateStore
from delegate.domain.accounts.profiles import LOGIN_CMD
from delegate.domain.policy.matchers import heredoc_only_hit
from delegate.domain.policy.worker import APPLY_PATCH_HINT
from delegate.domain.time.spec import local

LOGOUT_OUT = (
    900  # an account whose worker found it logged out is skipped this long, then tried again (a login in between is not seen sooner)
)
HUNG_OUT_SECS = 1800  # an account whose worker printed nothing at all rests this long
CREDIT_PROBE = 6 * 3600  # an account out of credits with no stated end is looked at again after this long
GUESS_WINDOW = 6 * 3600


def stop(fact: str, words: str) -> dict[str, Json]:
    """The answer of a stop this process measured itself (`setup_failed`, `crashed`, `signal`): the ladder names the reason, `words` is
    what it says. No account state changes."""
    o = classify(None, structured={fact: words})
    assert o is not None  # a caller fact always names a reason
    return {"outcome": o.reason, "say": o.detail}


def probe_hung(account: str, model: str, secs: float, t: float) -> dict[str, Json]:
    """A canary probe that did not answer in time: `timeout` is never counted, `hung` is, and the ladder names it from the watchdog fact.
    Nothing is marked out here; the pair tries again in a minute."""
    o = classify(None, structured={"watchdog": "hung"})
    assert o is not None
    return {"outcome": o.reason, "retry_after": t + 60, "say": f"canary: {account}/{model} did not answer within {secs}s"}


@dataclass(frozen=True)
class Hung:
    """A worker the watchdog stopped for silence: what it said (`words`) and when it went quiet (`kind`: first_event, or later)."""

    words: str
    kind: str


@dataclass
class Case:
    """One outcome being applied: the answer under construction and everything a reason's method may need."""

    res: dict[str, Json]
    o: Outcome
    d: dict[str, Json]
    t: float
    who: str
    a: Args
    rc: int | None = None
    tail: str = ""
    reset: Callable[[], float | None] | None = None
    login: tuple[str, str] | None = None
    answered: bool = False  # the final answer was captured before the run failed
    hung: Hung | None = None

    @property
    def account(self) -> str:
        return as_str(self.d["account"])

    @property
    def why(self) -> str:
        return self.o.detail.strip()


class Settler:
    def __init__(self, states: StateStore, net_up: Callable[[str], bool], clock: Callable[[], float], jitter: Callable[[], int]) -> None:
        self.states, self.net_up, self.clock, self.jitter = states, net_up, clock, jitter
        self.by_reason = {
            "secrets": self._secrets,
            "timeout": self._timeout,
            "hung": self._hung,
            "rate_limited": self._rate_limited,
            "credit_exhausted": self._credit_exhausted,
            "logged_out": self._logged_out,
            "bad_request": self._bad_request,
            "network": self._network,
            "killed": self._killed,
            "vendor_blip": self._vendor_blip,
        }

    def mark_out(
        self,
        account: str,
        until: float,
        why: str,
        t: float,
        reason: str = "limit",
        source: str = "guess",
        zone: str | None = None,
        guess_n: int = 0,
    ) -> None:
        """Record an account out. source: vendor (the vendor stated the end) | guess | manual (the owner said); zone: the zone the vendor's
        time was in;
        `set` = wall clock now (workers already running read it: an account marked out after they started stops them)."""
        self.states.update(
            lambda s: s.out.__setitem__(
                account, OutState(until=until, why=why, at=t, set=time.time(), reason=reason, source=source, zone=zone, guess_n=guess_n)
            )
        )

    def net_pass(self, o: Outcome, d: dict[str, Json]) -> Outcome:
        """The decision is `classify.with_network`; this only supplies the account's one probe."""
        return with_network(o, lambda: self.net_up(as_str(d["account"])))

    def apply(
        self,
        res: dict[str, Json],
        o: Outcome,
        d: dict[str, Json],
        t: float,
        who: str,
        a: Args,
        rc: int | None = None,
        tail: str = "",
        reset: Callable[[], float | None] | None = None,
        login: tuple[str, str] | None = None,
        hung: Hung | None = None,
    ) -> dict[str, Json]:
        c = Case(res, self.net_pass(o, d), d, t, who, a, rc, tail, reset, login, bool(res.pop("answered", False)), hung)
        res["outcome"] = c.o.reason
        if rc is not None:
            res["exit_code"] = rc
        res["detail"] = c.why[:240]  # Run moves it into history.jsonl (`say`); it never reaches the wire
        self.by_reason.get(c.o.reason, self._other)(c)
        return res

    def _soon(self) -> float:
        return self.clock() + self.jitter()

    def _secrets(self, c: Case) -> None:
        c.res.update(
            say=f"stopped: the worker ran a command on a secret path: {c.why[:200]}"
            + (f"; {APPLY_PATCH_HINT}" if heredoc_only_hit(c.why) else "")
        )

    def _timeout(self, c: Case) -> None:
        c.res.update(say=f"{c.who} did not finish within {c.a.timeout}s and was killed")

    def _hung(self, c: Case) -> None:
        words, kind = (c.hung.words, c.hung.kind) if c.hung else ("printed nothing", "first_event")
        if (
            kind == "first_event"
        # nothing came at all: the account is the suspect, it rests; a worker that went quiet mid-run is the pair's (the breaker counts
        # it)
        ):
            until = c.t + HUNG_OUT_SECS
            self.mark_out(c.account, until, f"hung: {words}", c.t, "hung")
            c.res.update(retry_after=until, say=f"{c.who} {words} and was stopped; {c.account} out until {local(until)}")
        else:
            c.res.update(retry_after=self._soon(), say=f"{c.who} {words} and was stopped (its whole process tree); retry")

    def _rate_limited(self, c: Case) -> None:
        prev = self.states.load().out.get(c.account)
        n = prev.guess_n + 1 if prev and prev.source == "guess" and c.t - prev.at < GUESS_WINDOW else 0
        until, source, zone = reset_parse.limit_until(c.why, c.t, c.d, c.reset, n)
        ours = c.o.source == "ours"
        self.mark_out(
            c.account,
            until,
            ("limit (opencode log): " if ours else "limit refusal: ") + c.why[:120].replace("\n", " "),
            c.t,
            "limit",
            source,
            zone,
            n if source == "guess" else 0,
        )
        c.res.update(
            retry_after=until,
            say=f"{c.account} hit a limit" + (f" ({c.why[:120]}); worker stopped, account" if ours else ";") + f" out until {local(until)}",
        )

    def _credit_exhausted(self, c: Case) -> None:
        until = c.t + CREDIT_PROBE
        self.mark_out(c.account, until, "out of credits: " + c.why[:120].replace("\n", " "), c.t, "credit", "guess")
        c.res.update(retry_after=None, say=f"{c.account} is out of credits ({c.why[:120]}); out until {local(until)}")

    def _logged_out(self, c: Case) -> None:
        cmd = LOGIN_CMD.get(c.account, "route.py doctor")
        hint, say = c.login or (f"logged out: run `{cmd}`", f"{c.who} is not logged in: {{why}}")
        self.mark_out(c.account, c.t + LOGOUT_OUT, hint, c.t, "logged_out", "guess")
        c.res.update(fix=f"run `{cmd}`", say=say.format(why=c.why[-200:].strip()))

    def _bad_request(self, c: Case) -> None:
        c.res.update(
            fix="the vendor rejected the request itself (schema, flags or arguments): fix the caller, not the account",
            say=f"{c.who} rejected the request: {c.why[:300]}",
        )

    def _network(self, c: Case) -> None:
        if c.answered:  # the final answer was captured before the connection dropped: the work is done, say so
            self.states.update(lambda s: s.out.pop(c.account, None))
            c.res.update(
                outcome=None, data=answer.parse_data(as_str(c.res.get("text")), c.a.schema), warnings=["net_after_answer"], detail=""
            )
        # not an account fault: nothing is marked out, the pair is not counted, and the caller decides when to resume (`resumable`, `ref`)
        else:
            c.res.update(
                retry_after=self._soon(),
                resumable=bool(c.res.get("ref") and c.res.get("started")),
                partial=bool(c.res.get("partial")),
                say=f"{c.who} could not reach its service: {c.why[-200:].strip()}",
            )

    def _killed(self, c: Case) -> None:
        if c.o.source == "ours":  # route.py's own signal: its words are the whole answer
            c.res.update(say=c.why)
            return
        c.res.update(
            resumable=bool(c.res.get("ref") and c.res.get("started")),
            partial=bool(c.res.get("partial")),
            say=f"{c.who} was ended by a signal it did not get from route.py ({c.why}); retry",
        )

    def _vendor_blip(self, c: Case) -> None:
        c.res.update(retry_after=self._soon(), say=f"{c.who} failed before any work: {c.why[:200]}")

    def _other(self, c: Case) -> None:
        c.res.update(
            say=f"{c.who}: {c.why[:300]}"
            if c.o.source == "event"
            else f"{c.who} exited {c.rc} without an error: {(c.why or c.tail)[-300:].strip()}"
        )
