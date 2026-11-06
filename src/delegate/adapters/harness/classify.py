"""The one outcome ladder : what a vendor CLI said -> one reason from contract.json.

Pure: no state, no I/O except reading contract.json once. The three launchers (codex, opencode, claude) collect evidence, call
`classify`, then apply the effects of the reason in one place (Settler.apply). Vendor text enters through `vendor_err` (the vendor's own
error event, or the CLI's own error result) and `stderr`; the model's answer text is never an argument, so a worker that says
"rate limit" cannot take its lane out.
"""

import re
from collections.abc import Callable, Mapping
from typing import NamedTuple

from delegate.contracts.json_types import Json

# ---- PATTERNS: every regex that turns vendor text into a reason lives here -----------------------------------------------------
LIMIT_RE = re.compile(r"usage limit|rate.?limit|quota|too many requests|\b429\b|try again (later|in)|credit balance", re.I)
CREDIT_RE = re.compile(
    r"spend(ing)?[- ]?(limit|control)|out of credits|credit balance|insufficient (funds|credit)|credits? (exhausted|too low)"
    r"|personal-team-blocked",
    re.I,
)
SPEND_RE = re.compile(CREDIT_RE.pattern + r"|top[- ]?up|billing|cycle cap|cap reached", re.I)  # cockpit: any prose that means money
LOGIN_RE = re.compile(
    r"not logged in|please (run|use) [`'\"]?\S*\s*login|oauth session expired|failed to authenticate|invalid api key|401 unauthorized", re.I
)
NETWORK_RE = re.compile(
    r"ENOTFOUND|ECONNRESET|ECONNREFUSED|ETIMEDOUT|EAI_AGAIN|getaddrinfo|could not resolve host|network is unreachable"
    r"|cannot connect to api|unable to connect",
    re.I,
)
CODEX_STATUS_RE = re.compile(
    r'"status":\s*4(?!29)\d\d'
)  # codex puts the HTTP status inside its error JSON; 429 is a limit, not a bad request
BAD_REQUEST_RE = re.compile(
    CODEX_STATUS_RE.pattern
    + r"|invalid_request_error|invalid_json_schema|Invalid schema for response_format|unrecognized arguments:|error: unknown argument"
    r"|no rollout found for thread|No conversation found with session ID",
    re.I,
)  # the vendor refused the request itself: schema, a flag its CLI no longer takes, or a --resume thread it does not know
# What a vendor or the OS says when the connection itself broke. `max_output_tokens` after "stream disconnected" is the model's cap, not
# the network.
DROP_RE = re.compile(
    r"ENOTFOUND|ECONNRESET|ECONNREFUSED|ECONNABORTED|ETIMEDOUT|EAI_AGAIN|EPIPE|getaddrinfo|could not resolve host|network is unreachable"
    r"|cannot connect to api|unable to connect|error sending request|connection (reset|closed|refused|timed out|failed)|socket hang up"
    r"|dns error|network error|waiting for network|(?:TLS|SSL) handshake|stream disconnected(?!.{0,200}max_output_tokens)",
    re.I | re.S,
)
NET_AMBIGUOUS = ("worker_failed", "vendor_blip", "hung")  # failures that name no cause of their own: the network may be it
PATTERNS = {
    "dropped": DROP_RE,
    "limit": LIMIT_RE,
    "credit": CREDIT_RE,
    "spend": SPEND_RE,
    "login": LOGIN_RE,
    "network": NETWORK_RE,
    "codex_status": CODEX_STATUS_RE,
    "bad_request": BAD_REQUEST_RE,
}


class Outcome(NamedTuple):
    reason: str
    detail: str
    source: str  # ours | event | stderr | exit


def _ours(s: Mapping[str, Json], timed_out: bool) -> Outcome | None:
    """The reasons only facts we measured ourselves give: a secret, the watchdog, our own timeout."""
    if s.get("secret"):
        return Outcome("secrets", str(s["secret"]), "ours")
    if s.get("watchdog") == "limit":
        msg = str(s.get("msg") or "")
        return Outcome("credit_exhausted" if CREDIT_RE.search(msg) else "rate_limited", msg, "ours")
    if s.get("watchdog") == "credit":  # another process marked the lane out for credit / login: its own words, not a guess from text
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


def _by_text(text: str, src: str, work_seen: bool) -> Outcome | None:
    """The reason the vendor's words give, first match wins."""
    if CREDIT_RE.search(text):
        return Outcome("credit_exhausted", text, src)
    if LIMIT_RE.search(text):
        return Outcome("rate_limited", text, src)
    if LOGIN_RE.search(text):
        return Outcome("logged_out", text, src)
    if BAD_REQUEST_RE.search(text):
        return Outcome("bad_request", text, src)
    if NETWORK_RE.search(text) and not work_seen:
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
) -> Outcome | None:
    """-> Outcome, or None when the run is done. First match wins.

    rc: exit code (negative = a signal); vendor_err: the vendor's error text from its event stream; stderr: the CLI's stderr; timed_out: our
    --timeout fired; work_seen: the worker did something before it failed; structured: facts we measured ourselves:
    {"secret": cmd, "watchdog": "limit"|"credit"|"logged_out"|"hung", "msg": log line, "http_status": int, "net_up": False}."""
    s = structured or {}
    vendor_event, code = (vendor_err or "").strip(), rc or 0
    ours = _ours(s, timed_out)
    if ours:
        return ours
    text = vendor_event + ("\n" + (stderr or "") if code != 0 else "")
    src = "event" if vendor_event else "stderr"
    return _by_status(s.get("http_status"), text, src) or _by_text(text, src, work_seen) or _by_exit(code, vendor_event, stderr, work_seen)


def looks_dropped(text: str | None) -> bool:
    """True when `text` (a vendor error event or stderr, never the model's answer) says the connection broke."""
    return bool(DROP_RE.search(text or ""))


def with_network(o: Outcome, net_up: Callable[[], bool]) -> Outcome:
    """`o`, or the network outcome when it was the network. `classify` trusts network words only before the worker did anything, and a
    silent hang is only a network drop if the net is down: a failure with no cause of its own is checked against the words of a dropped
    connection, then against one probe (`net_up`). Limits, logins, bad requests, secrets and timeouts are never second-guessed."""
    if o.reason in NET_AMBIGUOUS and (looks_dropped(o.detail) or not net_up()):
        return Outcome("network", o.detail, o.source)
    return o


def network_stop(evidence: str) -> Outcome:
    """The outcome of a worker we stopped because the net probe stayed down: the harness's own words for a transient failure."""
    return Outcome("network", evidence, "event")


def says_login(text: str):
    return bool(LOGIN_RE.search(text))


def says_spend(text: str):
    return bool(SPEND_RE.search(text))


def limit_words(text: str, top: str | None):
    """The window a limit message names ("weekly limit hit"), else `top` (the fullest window's name) or the plain words."""
    if re.search(r"free usage", text, re.I):
        return "free usage limit reached"
    for pat, word in ((r"week|7.?day", "weekly"), (r"5.?hour|five.?hour", "5-hour"), (r"daily|per day|\bday\b", "daily")):
        if re.search(pat, text, re.I):
            return f"{word} limit hit"
    return f"{top} limit hit" if top else "usage limit hit"
