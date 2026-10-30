"""Why a run moved from one step to the next, in words: the arrow into a block and the line a run ends with."""

import itertools
from typing import Final, assert_never

from taskloop.contracts.checks import RoundVerdict, round_verdict_of
from taskloop_dash.jsonrec import Json
from taskloop_dash.views.names import hhmm, lane_name


def words(text: str) -> list[str]:
    """The text split on anything that is not a letter, digit or '_'."""
    return "".join(c if c.isalnum() or c == "_" else " " for c in text).split()


def lead_int(text: str) -> str:
    """The digits a text starts with."""
    n = 0
    while n < len(text) and text[n].isdigit():
        n += 1
    return text[:n]


def lane_of(why: str) -> str:
    """The lane a pause text names (an UPPER_CASE_WORD with an underscore), as Codex, Claude or Grok."""
    for w in words(why or ""):
        if "_" in w and w.replace("_", "").isalpha() and w.isupper() and not w.startswith("_"):
            return lane_name(w)
    return ""


def until_of(why: str) -> str:
    """The HH:MM after the word 'until'."""
    toks = (why or "").split()
    for a, b in itertools.pairwise(toks):
        hh, _, mm = b[:5].partition(":")
        if a == "until" and len(b) >= 5 and hh.isdigit() and len(hh) == 2 and mm.isdigit() and len(mm) == 2 and not b[5:6].isalnum():
            return b[:5]
    return ""


def pause_reason(why: str) -> str:
    """What a pause waits for, in a few words: "Codex out", "Claude logged out", "no network"."""
    if "logged_out" in why:
        return "%s logged out" % ("Codex" if "codex login" in why else "Grok" if "opencode auth login" in why else "Claude")
    if why.startswith("paused: no network") or "(network" in why:
        return "no network"
    if "setup on" in why or "(setup" in why:
        return "delegate needs setup"
    lane = lane_of(why)
    return f"{lane} out" if lane else "no lane"


def ask_kind(why: str) -> str | None:
    if why.startswith(("paused:", "waiting:", "failed:")):
        return None
    for head, kind in (
        ("owner decision needed", "decision"),
        ("over budget", "budget"),
        ("needs a human", "denied"),
        ("verify:", "verify"),
        ("ticket:", "ticket"),
    ):
        if why.startswith(head):
            return kind
    return "stuck"


def close_move(outcome: str, why: str) -> tuple[str, str]:
    if outcome in ("landed", "done"):
        return "close", outcome
    if why.startswith("paused:"):
        return "pause", "paused"
    if why.startswith("waiting:"):
        return "ask", "waiting"
    kind = ask_kind(why) if outcome == "blocked" else None
    if kind:
        return "ask", kind
    return "close", "stopped" if why.startswith("failed: stopped") else "failed"


def same_round(a: Json, b: Json) -> bool:
    """b writes again for the stage (or fix) a judged: a send-back, not the next stage."""
    ka, kb = (a["meta"].get("stage"), a["meta"].get("fix")), (b["meta"].get("stage"), b["meta"].get("fix"))
    return ka == kb and (b["meta"].get("write") or 1) > 1


def mv(to: str, cause: str, detail: str = "") -> Json:
    return {"to": to, "cause": cause, "detail": detail}


def after_checks(a: Json, b: Json) -> Json | None:
    verdict = round_verdict_of(a["outcome"])
    if verdict is None:
        return None
    match verdict:
        case RoundVerdict.RED:
            return mv(b["step"], "checks_red" if b["step"] == "write" else "rounds_used", a["detail"])
        case RoundVerdict.UNVERIFIED | RoundVerdict.GREEN:
            if b["step"] != "review":
                return None
            return mv("review", "checks_unverified" if verdict is RoundVerdict.UNVERIFIED else "checks_green", a["detail"])
        case _:
            assert_never(verdict)


def after_review(a: Json, b: Json) -> Json | None:
    sb = b["step"]
    if sb == "write" and same_round(a, b):
        return mv("write", "review_sendback", a["detail"])
    if sb in ("write", "verify", "land"):
        return mv(sb, "accepted")
    return mv(sb, "rounds_used", a["detail"]) if sb in ("plan", "replan") else None


def after_land(a: Json, b: Json) -> Json | None:
    return {"land": mv("land", "push_race"), "write": mv("fix", "gate_red")}.get(b["step"])


def infer_move(a: Json, b: Json) -> Json | None:
    """The move from node a to node b when no transition record says it."""
    sa, sb = a["step"], b["step"]
    if sb == "close":
        why = b["close"].get("why") or ""
        to, cause = close_move(b["close"].get("outcome") or "", why)
        return mv(to, cause, why.split("\n")[0])
    if sa in ("plan", "replan"):
        return mv("write", "planned", a["outcome"]) if sb == "write" else None
    if sa == "verify":
        return mv(sb, "verify_wrong" if sb == "write" else "verified", a["detail"])
    after = {"checks": after_checks, "review": after_review, "land": after_land}.get(sa)
    return after(a, b) if after else None


def sendback_prefix(detail: str) -> str:
    """'3 findings, 1 unmet' from the start of a review's detail, else ''."""
    head, _, rest = detail.partition(", ")
    n, m = lead_int(head), lead_int(rest)
    if n and m and head[len(n) :] in (" finding", " findings") and rest[len(m) :].startswith(" unmet"):
        return f"{head}, {m} unmet"
    return ""


def round_of(detail: str) -> str:
    toks = detail.split()
    for a, b in itertools.pairwise(toks):
        if a == "round" and lead_int(b):
            return lead_int(b)
    return ""


ASKS: Final = {
    "decision": "decision needed",
    "verify": "needs your check",
    "ticket": "needs a split or criteria",
    "stuck": "stuck",
    "waiting": "waiting for your answer",
    "verify_open": "needs your check",
    "needs_human": "needs you",
    "denied": "needs you",
    "budget": "over its time limit",
}
FIXED: Final = {
    "checks_green": "checks green",
    "checks_unverified": "checks unverified: review goes on, the land refuses",
    "accepted": "accepted",
    "bad_checks": "writer: the checks are wrong → re-plan",
    "rounds_used": "rounds used up → re-plan",
    "writer_decided": "a requirement already decides it → write again",
    "lane_wait": "waited for a lane",
    "invalid_output": "invalid output → try again",
    "plan_sent_back": "checks sent back → plan again",
    "verify_wrong": "check before land found defects → fix round",
    "verified": "verified → land",
    "gate_red": "gate red → fix round",
    "conflict": "merge conflict → fix round",
    "push_race": "main moved → push again",
    "landed": "landed",
    "done": "done",
    "stopped": "stopped",
}


def red_text(detail: str) -> str:
    first = detail.split(";", maxsplit=1)[0]
    n = lead_int(first)
    what = f"{n} failed" if n and first[len(n) :].startswith(" failed") else "failed"
    return f"checks red: {what} → write again"


def sendback_text(detail: str) -> str:
    n, r = sendback_prefix(detail), round_of(detail)
    return f"review sent back{(': ' + n) if n else ''} → round {r or 'again'}"


def lane_out_text(ctx: Json) -> str:
    return f"{ctx.get('from_name') or 'the lane'} out → new thread{(' on ' + ctx['to_model']) if ctx.get('to_model') else ''}"


def paused_text(detail: str, ctx: Json) -> str:
    what = f"{ctx['lane']} out" if ctx.get("lane") else pause_reason(detail)
    until = ctx.get("until") or until_of(detail)
    return f"{what} → paused{(' until ' + until) if until else ''}"


def arrow_text(cause: str, detail: str | None = "", ctx: Json | None = None) -> str:
    """What the arrow into a block (or the run's end) says."""
    ctx = ctx or {}
    detail = (detail or "").strip()
    text = {
        "checks_red": lambda: red_text(detail),
        "review_sendback": lambda: sendback_text(detail),
        "planned": lambda: detail or "planned",
        "lane_out": lambda: lane_out_text(ctx),
        "paused": lambda: paused_text(detail, ctx),
        "failed": lambda: "failed: " + detail[:120] if detail else "failed",
    }.get(cause)
    if text:
        return text()
    if cause in ASKS:
        return ASKS[cause] + " → asks you"
    return FIXED.get(cause) or cause.replace("_", " ")


def stage_title(goal: object, cap: int = 80) -> str:
    """A stage's title from its plan goal: the first sentence, before a leading `Name:`, cut at a word."""
    t = str(goal or "").strip().split("\n")[0].strip()
    for i, c in enumerate(t):  # the first '.' after a character that is neither '.' nor space, followed by a space or the end
        if c == "." and i and t[i - 1] != "." and not t[i - 1].isspace() and (i + 1 == len(t) or t[i + 1].isspace()):
            t = t[:i].strip()
            break
    colon = t.find(":")
    if 3 <= colon <= 40 and "`" not in t[:colon] and colon + 1 < len(t) and t[colon + 1].isspace():
        t = t[:colon].strip()
    if len(t) > cap:
        t = t[:cap].rsplit(" ", 1)[0].rstrip(",;:- ") + "…"
    return t


def exit_ctx(mv: Json) -> Json:
    until = mv.get("until")
    return {"lane": lane_name(mv.get("lane") or "") or None, "until": hhmm(until) if isinstance(until, (int, float)) and until else None}
