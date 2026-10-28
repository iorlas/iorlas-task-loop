"""The inbox: the open asks, most unblocking first, and the owner's two writes, an answer and a withdrawal. Both are typed: an answer is an
AskAnswer filed on the ask through the AskStore (first answer wins), a withdrawal a status. Only the current ask version is read; an old
or unknown one is absent. The text of a card comes from the record's fields (the launcher's `ask_text` port renders it)."""

import subprocess
import threading
from pathlib import Path
from typing import Any, Final

from taskloop.contracts import codec
from taskloop.contracts.ask import Ask as AskRecord
from taskloop.contracts.ask import AskAnswer
from taskloop.contracts.stores import ORPHAN, AskStore
from taskloop_dash.api.lanes import Lanes
from taskloop_dash.env import Env
from taskloop_dash.readers.beads import Beads, basename
from taskloop_dash.views import graph

Ask = dict[str, Any]
Reply = tuple[int, dict[str, Any]]
GONE: Reply = (404, {"code": "gone", "error": "This ask no longer exists."})
PROBLEMS: Final = {
    "withdrawn": (410, "The engine withdrew this ask. Nothing to answer."),
    "closed": (410, "This ask is closed: its bead is closed or gone. Nothing to answer."),
    "consumed": (409, "A run already used the answer to this ask; comment on the bead to say more."),
    "answered": (409, "This ask is already answered. To replace the answer before a run uses it: tl ask answer BEAD --amend <text> "
                      "(or Change answer on the dashboard)."),
    "superseded": (409, "The engine asked again for this bead; the new ask replaces this one."),
}


def bd_failed(a: AskRecord, r: "subprocess.CompletedProcess[str]") -> Reply:
    out = ((r.stderr or "") + (r.stdout or "")).strip()
    if "no issue found" in out or "not found" in out.lower():
        return 404, {"code": "bead_missing", "error": "The bead %s no longer exists in %s. The ask is out of date: dismiss it."
                     % (a.bead, basename(a.repo) or "its repo")}
    return 502, {"code": "bd", "error": "bd refused the update: %s" % (out.splitlines()[-1][:200] if out else "no output")}


def next_step(a: AskRecord) -> str:
    return "The bead %s runs again from your answer on the next pass of the loop for %s." % (a.bead, basename(a.repo) or "its repo")


class Asks:
    def __init__(self, env: Env, beads: Beads, lanes: Lanes) -> None:
        self.env, self.beads, self.lanes = env, beads, lanes
        self.store = AskStore.at(env.config)

    def ask_file(self, bead: str) -> Ask:
        """The bead's ask as a dict ({} when it has none or the file is not this version)."""
        a = self.store.get(bead)
        return codec.to_json(a) if a else {}

    def view(self, a: AskRecord) -> Ask:
        """The ask as the page reads it: the card text rendered from the fields, the options as buttons."""
        out = codec.to_json(a)
        out["question"] = self.env.ports.ask_text(a)
        out["detail"] = a.detail.text if a.detail.text.strip() != a.decision else ""
        out["answer"] = (a.answer.text or a.answer.action) if a.answer else None
        out["options"] = [{"label": o.label, "answer": o.text or o.label, "then": o.consequence, "cost": o.cost, "recommended": o.recommended,
                           "edit": o.edit, "action": o.action} for o in a.options]
        return out

    def open_ask(self, bead: str) -> Ask | None:
        a = self.store.get(bead)
        if a is None or a.consumed is not None or a.status.value not in ("open", "parked"):
            return None
        v = self.view(a)
        return {k: v.get(k) for k in ("id", "kind", "question", "detail", "t", "title", "answer", "repo", "parks_at", "options")} | {"unblocks": None}

    def unblocks_by_bead(self, repo: str) -> dict[str, Any] | None:
        """bead id -> how many open beads wait on it (directly or through others), from bd list (cached by beads_of)."""
        try:
            beads = self.beads.beads_of(repo)
        except Exception:
            return None
        if not beads:
            return None
        by_id = {b["id"]: b for b in beads}
        edges: dict[str, set[str]] = {}
        for t, b in by_id.items():
            if b.get("status") == "closed":
                continue
            for s in graph.blockers(b):
                if s in by_id and s != t and by_id[s].get("status") != "closed":
                    edges.setdefault(s, set()).add(t)
        epics = {i for i, b in by_id.items() if b.get("issue_type") == "epic"}
        return {"counts": graph.unblock_counts(edges, epics), "known": set(by_id), "open": {i for i, b in by_id.items() if b.get("status") != "closed"}}

    def inbox(self) -> list[Ask]:
        """The asks waiting for the owner or for the next run, most unblocking first. An ask whose bead is gone or closed is never shown."""
        out: list[Ask] = []
        now: float = self.env.clock()
        ub: dict[str, dict[str, Any] | None] = {}
        todo = self.store.pending()
        repos = {a.repo for a in todo if a.repo and (Path(a.repo) / ".beads").exists()}
        if len(repos) > 1:  # the bd reads of several repos run side by side
            ts = [threading.Thread(target=self.unblocks_by_bead, args=(r,), daemon=True) for r in repos]
            for t in ts:
                t.start()
            for t in ts:
                t.join(32)
        for a in todo:
            if a.repo not in ub:
                ub[a.repo] = self.unblocks_by_bead(a.repo) if a.repo and (Path(a.repo) / ".beads").exists() else None
            info = ub[a.repo]
            if info and a.bead not in info["open"] and (a.bead in info["known"] or now - a.t > 600):
                continue  # closed, or gone for good (a bead newer than a stale listing is not gone yet)
            v = self.view(a)
            v["age_s"] = int(now - a.t)
            v["parked"] = a.status.value == "parked" or now > (a.parks_at or now + 1)
            v["answered_here"] = a.answer is not None
            v["unblocks"] = info["counts"].get(a.bead, 0) if info else 0
            v["quick"] = bool(a.options) and a.kind.value != "decision"
            out.append(v)
        out.sort(key=lambda a: (a["parked"], a["answered_here"], -a["unblocks"], not a["quick"], -a["age_s"]))
        return out + [self.orphan_row(b) for b in self.store.orphans()]

    def orphan_row(self, bead: str) -> Ask:
        """A bead parked on an ask that was dropped at upgrade: one line, nothing to answer here (`tl answer --rerun` re-asks)."""
        return {"id": f"{bead}-0", "bead": bead, "kind": "stuck", "question": ORPHAN, "detail": "", "t": 0, "title": "", "answer": None,
                "repo": "", "parks_at": None, "options": [], "age_s": 0, "parked": True, "answered_here": False, "unblocks": 0,
                "quick": False, "orphan": True}

    def asks(self) -> dict[str, Any]:
        return {"asks": self.inbox(), "delegate": self.lanes.delegate_status()}

    def find(self, ask_id: object) -> tuple[AskRecord | None, str]:
        """(the ask, "") when `ask_id` is the bead's current ask, else (the bead's ask or None, why not)."""
        ask_id = ask_id if isinstance(ask_id, str) else ""
        bead = ask_id.rsplit("-", 1)[0]
        if not bead or "/" in bead or ".." in bead:
            return None, "gone"
        return self.store.state(bead, ask_id)

    def refuse(self, why: str) -> Reply:
        if why == "gone" or why not in PROBLEMS:
            return GONE
        code, error = PROBLEMS[why]
        return code, {"code": why, "error": error}

    def answer(self, body: object) -> Reply:
        """First answer wins: an AskAnswer on the ask, and the bead opened for the loop. `option` picks one of the ask's own options
        (its typed action and text); otherwise the words are a text answer."""
        a, refused = self.target(body)
        if a is None or not isinstance(body, dict):
            return refused or GONE
        amend = body.get("amend") is True
        text = body.get("text") if isinstance(body.get("text"), str) else ""
        text = text.strip()
        opt = body.get("option")
        action = "text"
        if isinstance(opt, int) and 0 <= opt < len(a.options):
            o = a.options[opt]
            action, text = o.action, " ".join(x for x in (o.text or (o.label if o.action == "text" else ""), text) if x)
        if not text and action == "text":
            return 400, {"code": "empty", "error": "Write an answer first."}
        given = AskAnswer(action=action, text=text, t=self.env.clock(), by="dash")  # type: ignore[arg-type]
        _done, why = (self.store.amend if amend else self.store.answer)(a.bead, a.id, given)
        if why:
            return self.refuse(why)
        return self.open_bead(a) or (200, {"ok": True, "bead": a.bead, "next": next_step(a)})

    def target(self, body: object) -> tuple[AskRecord | None, Reply | None]:
        """(the ask an answer is for, None) or (None, why it cannot be answered). An answered ask is a target only for an amend."""
        if not isinstance(body, dict):
            return None, (400, {"code": "bad_body", "error": "The request was not understood."})
        a, why = self.find(body.get("ask"))
        if a is not None and (not why or (body.get("amend") is True and why == "answered")):
            return a, None
        if why == "superseded" and a is not None:
            return None, (409, {"code": why, "new_ask": a.id, "error": PROBLEMS[why][1]})
        return None, self.refuse(why or "gone")

    def open_bead(self, a: AskRecord) -> Reply | None:
        """Open the bead for the loop. -> None when done, else the reply that says what went wrong."""
        try:
            r = self.env.ports.bd(a.repo or None, "update", a.bead, "--status", "open")
        except OSError as e:
            return 502, {"code": "no_bd", "error": f"The answer is saved, but the dashboard cannot run bd to open the bead ({e.strerror})."}
        return bd_failed(a, r) if r.returncode else None

    def withdraw(self, body: object) -> Reply:
        """The owner dismisses an ask that no longer applies; the bead is not touched."""
        if not isinstance(body, dict):
            return 400, {"code": "bad_body", "error": "The request was not understood."}
        a, why = self.find(body.get("ask"))
        if a is None:
            return self.refuse(why or "gone")
        if why in ("withdrawn", "closed"):
            return 200, {"ok": True}
        if why in ("superseded", "consumed"):
            return self.refuse(why)
        reason = body.get("why") if isinstance(body.get("why"), str) and body.get("why").strip() else "dismissed by the owner"
        _done, why = self.store.withdraw(a.bead, a.id, reason, self.env.clock())
        return self.refuse(why) if why else (200, {"ok": True})
