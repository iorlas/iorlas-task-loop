"""The one outcome ladder: what a vendor CLI said -> one reason string.

Pure: no state, no I/O. The caller collects the harness's evidence, calls `classify`, then applies the effects of the reason in one place.
The generic words (limit, credit, login, network) are here; each harness module owns the patterns only its CLI speaks and the ladder merges
them. Vendor text enters through `vendor_err` (the vendor's own
error event, or the CLI's own error result) and `stderr`; the model's answer text is never an argument, so a worker that says
"rate limit" cannot take its lane out.
"""

import re
from collections.abc import Callable, Mapping
from functools import cache
from typing import NamedTuple

from any_agent import drops, vendors
from any_agent._json import Json


# ---- PATTERNS: what vendors say lives in any_agent.vendors, what only a CLI says in its harness module ---------------------------
def _cli_bad_request() -> tuple[str, ...]:
    from any_agent.harnesses import claude, codex  # noqa: PLC0415 - harness modules do not import the ladder, but keep the edge lazy

    return (*codex.BAD_REQUEST_PATTERNS, *claude.BAD_REQUEST_PATTERNS)  # a --resume thread the CLI does not know, a 4xx body it forwards


@cache
def _ladder_words(vendor_names: tuple[str, ...]) -> vendors.Words:
    w = vendors.words(vendor_names)
    bad = re.compile(w.bad_request.pattern + "|" + "|".join(_cli_bad_request()), re.IGNORECASE)
    return vendors.Words(limit=w.limit, credit=w.credit, spend=w.spend, login=w.login, network=w.network, bad_request=bad)


NET_AMBIGUOUS = ("worker_failed", "vendor_blip", "hung")  # failures that name no cause of their own: the network may be it


class Outcome(NamedTuple):
    reason: str
    detail: str
    source: str  # ours | event | stderr | exit


def _ours(s: Mapping[str, Json], timed_out: bool, w: vendors.Words) -> Outcome | None:
    """The reasons only facts we measured ourselves give: a secret, the watchdog, our own timeout."""
    if s.get("secret"):
        return Outcome("secrets", str(s["secret"]), "ours")
    if s.get("watchdog") == "limit":
        msg = str(s.get("msg") or "")
        return Outcome("credit_exhausted" if w.credit.search(msg) else "rate_limited", msg, "ours")
    if s.get("watchdog") == "credit":  # another process marked the lane out: its own words, not a guess from text
        return Outcome("credit_exhausted", str(s.get("msg") or ""), "ours")
    if s.get("watchdog") == "logged_out":
        return Outcome("logged_out", str(s.get("msg") or ""), "ours")
    if s.get("watchdog") == "hung":
        return Outcome("network" if s.get("net_up") is False else "hung", "", "ours")
    return Outcome("timeout", "", "ours") if timed_out else None


def _by_status(http: Json, text: str, src: str) -> Outcome | None:
    """The reason a 4xx status we measured gives."""
    if not isinstance(http, int) or not 400 <= http < 500:
        return None
    if http == 429:
        return Outcome("rate_limited", text, src)
    if http in (401, 403):
        return Outcome("logged_out", text, src)
    return Outcome("bad_request", text, src)


def _by_text(text: str, src: str, work_seen: bool, w: vendors.Words) -> Outcome | None:
    """The reason the vendor's words give, first match wins."""
    if w.credit.search(text):
        return Outcome("credit_exhausted", text, src)
    if w.limit.search(text):
        return Outcome("rate_limited", text, src)
    if w.login.search(text):
        return Outcome("logged_out", text, src)
    if w.bad_request.search(text):
        return Outcome("bad_request", text, src)
    if w.network.search(text) and not work_seen:
        return Outcome("network", text, src)
    return None


def _by_exit(rc: int, vendor_event: str, stderr: str | None, work_seen: bool) -> Outcome | None:
    """The reason the exit code and the vendor's error event give when no words matched."""
    if rc < 0 and not vendor_event:
        return Outcome("killed", f"signal {-rc}", "exit")
    if vendor_event:
        return Outcome("worker_failed" if work_seen else "vendor_blip", vendor_event, "event")
    if rc != 0:
        tail = (stderr or "").strip()
        return Outcome("worker_failed", tail, "stderr" if tail else "exit")
    return None


def classify(
    rc: int | None,
    vendor_err: str | None = "",
    stderr: str | None = "",
    timed_out: bool = False,
    work_seen: bool = False,
    structured: Mapping[str, Json] | None = None,
    only: tuple[str, ...] = (),
) -> Outcome | None:
    """-> Outcome, or None when the run is done. First match wins.

    rc: exit code (negative = a signal); vendor_err: the vendor's error text from its event stream; stderr: the CLI's stderr; timed_out: our
    --timeout fired; work_seen: the worker did something before it failed; structured: facts we measured ourselves:
    {"secret": cmd, "watchdog": "limit"|"credit"|"logged_out"|"hung", "msg": log line, "http_status": int, "net_up": False};
    only: vendor names whose words count
    beside `common` and the CLIs' own (none = every registered vendor)."""
    s = structured or {}
    vendor_event, code = (vendor_err or "").strip(), rc or 0
    w = _ladder_words(tuple(sorted(only)))
    ours = _ours(s, timed_out, w)
    if ours:
        return ours
    text = vendor_event + ("\n" + (stderr or "") if code != 0 else "")
    src = "event" if vendor_event else "stderr"
    return (
        _by_status(s.get("http_status"), text, src) or _by_text(text, src, work_seen, w) or _by_exit(code, vendor_event, stderr, work_seen)
    )


def with_network(o: Outcome, net_up: Callable[[], bool]) -> Outcome:
    """`o`, or the network outcome when it was the network. `classify` trusts network words only before the worker did anything, and a
    silent hang is only a network drop if the net is down: a failure with no cause of its own is checked against the words of a dropped
    connection, then against one probe (`net_up`). Limits, logins, bad requests, secrets and timeouts are never second-guessed."""
    if o.reason in NET_AMBIGUOUS and (drops.looks_dropped(o.detail) or not net_up()):
        return Outcome("network", o.detail, o.source)
    return o


def network_stop(evidence: str) -> Outcome:
    """The outcome of a worker we stopped because the net probe stayed down: the harness's own words for a transient failure."""
    return Outcome("network", evidence, "event")


def says_login(text: str, only: tuple[str, ...] = ()) -> bool:
    return bool(_ladder_words(tuple(sorted(only))).login.search(text))


def says_spend(text: str, only: tuple[str, ...] = ()) -> bool:
    return bool(_ladder_words(tuple(sorted(only))).spend.search(text))


def limit_words(text: str, top: str | None) -> str:
    """The window a limit message names ("weekly limit hit"), else `top` (the fullest window's name) or the plain words."""
    if re.search(r"free usage", text, re.IGNORECASE):
        return "free usage limit reached"
    for pat, word in ((r"week|7.?day", "weekly"), (r"5.?hour|five.?hour", "5-hour"), (r"daily|per day|\bday\b", "daily")):
        if re.search(pat, text, re.IGNORECASE):
            return f"{word} limit hit"
    return f"{top} limit hit" if top else "usage limit hit"
