"""The inbox: the open asks, most unblocking first, and the owner's two writes, an answer and a withdrawal. An answer is a comment on
the bead (the engine reads it as the bead changing) plus the answer in the ask file; first answer wins."""

import glob
import json
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

from taskloop_dash.api.lanes import Lanes
from taskloop_dash.env import Env
from taskloop_dash.readers.beads import Beads, basename
from taskloop_dash.tails import read_dict
from taskloop_dash.views import graph

Ask = dict[str, Any]
Reply = tuple[int, dict[str, Any]]
PLAIN_ANSWERS: Final = {"right", "run again", "allow one more", "yes", "ok"}
OPEN = ("open", "parked")
SHOWN = ("id", "kind", "question", "detail", "unblocks", "t", "title", "answer", "repo", "parks_at", "options")


def heading_end(notes: str, head: str) -> int:
    """Where the line that is exactly `head` (trailing blanks allowed) ends; -1 when none is: not ### and not a mention."""
    pos = 0
    for ln in notes.split("\n"):
        if ln.rstrip(" \t") == head:
            return pos + len(ln)
        pos += len(ln) + 1
    return -1


def bd_failed(a: Ask, r: "subprocess.CompletedProcess[str]") -> Reply:
    out = ((r.stderr or "") + (r.stdout or "")).strip()
    if "no issue found" in out or "not found" in out.lower():
        return 404, {"code": "bead_missing", "error": "The bead %s no longer exists in %s. The ask is out of date: dismiss it."
                     % (a.get("bead"), basename(a.get("repo")) or "its repo")}
    return 502, {"code": "bd", "error": "bd refused the comment: %s" % (out.splitlines()[-1][:200] if out else "no output")}


def next_step(a: Ask) -> str:
    """One sentence on what happens after the answer, for the confirmation."""
    return "The bead %s runs again from your answer on the next pass of the loop for %s." % (a.get("bead"), basename(a.get("repo")) or "its repo")


class Asks:
    def __init__(self, env: Env, beads: Beads, lanes: Lanes) -> None:
        self.env, self.beads, self.lanes = env, beads, lanes

    def ask_files(self) -> Iterator[tuple[str, Ask]]:
        for f in glob.glob(str(self.env.config.asks_dir() / "*.json")):
            a = read_dict(f)
            if a.get("v") == 1:
                yield f, a

    def ask_file(self, bead: str) -> Ask:
        return read_dict(self.env.config.ask(bead))

    def open_ask(self, bead: str) -> Ask | None:
        a = self.ask_file(bead)
        if a.get("status") not in OPEN:
            return None
        return {k: a.get(k) for k in SHOWN}

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
        """The open asks, most unblocking first. An ask whose bead is gone or closed is stale and never shown."""
        out: list[Ask] = []
        now: float = self.env.clock()
        ub: dict[str, dict[str, Any] | None] = {}
        todo = [(f, a) for f, a in self.ask_files() if a.get("status") in OPEN]
        repos = {a["repo"] for _, a in todo if isinstance(a.get("repo"), str) and (Path(a["repo"]) / ".beads").exists()}
        if len(repos) > 1:  # the bd reads of several repos run side by side
            ts = [threading.Thread(target=self.unblocks_by_bead, args=(r,), daemon=True) for r in repos]
            for t in ts:
                t.start()
            for t in ts:
                t.join(32)
        for _f, a in todo:
            repo = a.get("repo") if isinstance(a.get("repo"), str) else ""
            if repo not in ub:
                ub[repo] = self.unblocks_by_bead(repo) if repo and (Path(repo) / ".beads").exists() else None
            info = ub[repo]
            if info and a.get("bead") not in info["open"] and (a.get("bead") in info["known"] or now - float(a.get("t") or now) > 600):
                continue  # closed, or gone for good (a bead newer than a stale listing is not gone yet)
            a = {k: v for k, v in a.items() if k != "brief"}
            a["age_s"] = int(now - float(a.get("t") or now))
            a["parked"] = a.get("status") == "parked" or now > float(a.get("parks_at") or now + 1)
            a["answered_here"] = bool(a.get("answer"))
            a["unblocks"] = info["counts"].get(a.get("bead"), 0) if info else 0
            a["quick"] = bool(a.get("options")) and a.get("kind") != "decision"
            out.append(a)
        out.sort(key=lambda a: (a["parked"], a["answered_here"], -a["unblocks"], not a["quick"], -a["age_s"]))
        return out

    def asks(self) -> dict[str, Any]:
        return {"asks": self.inbox(), "delegate": self.lanes.delegate_status()}

    def ask_for(self, ask_id: object, amend: bool = False, withdrawing: bool = False) -> tuple[str | None, Ask | None, Reply | None]:
        """(path, ask, problem): the file that holds ask_id, or why it cannot be answered. Ask files are per bead and the engine
        overwrites them with a newer ask (id bead-n), so an id the file no longer carries is `superseded`."""
        ask_id = ask_id if isinstance(ask_id, str) else ""
        for f, a in self.ask_files():
            if a.get("id") != ask_id:
                continue
            if a.get("status") == "withdrawn":
                why = (a.get("withdrawn_why") or "").strip()
                return f, a, (410, {"code": "withdrawn", "error": "The engine withdrew this ask%s. Nothing to answer." % ((" (" + why + ")") if why else "")})
            if a.get("status") not in OPEN:
                return f, a, (409, {"code": "consumed" if amend else "answered",
                                    "error": "A run already used the answer to this ask; comment on the bead to say more." if amend
                                    else "This ask is already answered."})
            if a.get("answer") and not amend and not withdrawing:
                return f, a, (409, {"code": "answered", "error": "This ask is already answered. To replace the answer before a run "
                                    "uses it: tl ask answer %s --amend <text> (or Change answer on the dashboard)." % a.get("bead")})
            return f, a, None
        bead = ask_id.rsplit("-", 1)[0]
        now = self.ask_file(bead) if bead and "/" not in bead and "\\" not in bead and ".." not in bead else {}
        if now.get("id") and now.get("status") in OPEN:
            return None, None, (409, {"code": "superseded", "new_ask": now["id"],
                                      "error": "The engine asked again for this bead; the new ask replaces this one."})
        return None, None, (404, {"code": "gone", "error": "This ask no longer exists."})

    def answer(self, body: object) -> Reply:
        """First answer wins: a comment on the bead (the engine reads it as the bead changing) and the bead opened."""
        if not isinstance(body, dict):
            return 400, {"code": "bad_body", "error": "The request was not understood."}
        amend = body.get("amend") is True
        f, a, problem = self.ask_for(body.get("ask"), amend)
        if problem or f is None or a is None:
            return problem or (404, {"code": "gone", "error": "This ask no longer exists."})
        text = body.get("text")
        text = text.strip() if isinstance(text, str) else ""
        if not text:
            return 400, {"code": "empty", "error": "Write an answer first."}
        cwd = a.get("repo") or None
        amend = amend and bool(a.get("answer"))  # nothing to replace: it is a first answer
        try:
            r = subprocess.run(["bd", "comments", "add", a["bead"],
                                ("Answer amended (replaces the one above, not used yet): " + text) if amend else text],
                               cwd=cwd, capture_output=True, text=True)
            if r.returncode:
                return bd_failed(a, r)
            self.file_answer(a, text, cwd, amend)
            subprocess.run(["bd", "update", a["bead"], "--status", "open"], cwd=cwd, capture_output=True, text=True)
        except OSError as e:
            return 502, {"code": "no_bd", "error": "The dashboard cannot run bd (%s). Nothing was sent." % e.strerror}
        return self.save_answer(f, a, text, amend)

    def save_answer(self, f: str, a: Ask, text: str, amend: bool) -> Reply:
        try:  # the bd calls took seconds: re-read, so a run that started meanwhile (status answered) is not undone by a stale copy
            cur = json.loads(Path(f).read_text())
            if cur.get("id") != a.get("id"):  # a newer ask replaced this one: the answer was for the old one, nothing is written
                return 409, {"code": "superseded", "new_ask": cur.get("id"),
                             "error": "The engine asked again while this was sent; the new ask replaces this one. Your text is a comment on the bead."}
        except (OSError, ValueError):
            cur = a
        if cur.get("status") not in OPEN:
            if amend:
                return 409, {"code": "consumed", "error": "Too late: a run started on the first answer while you replaced it. "
                             "Your new text is a comment on the bead; the next run reads it."}
            return 200, {"ok": True, "bead": a["bead"], "next": next_step(a)}  # a first answer the run already picked up from the comment
        now = self.env.clock()
        if amend:  # the history stays: every answer given, oldest first
            cur["answers"] = list(cur.get("answers") or [{"text": cur.get("answer"), "t": cur.get("answer_t")}]) + [{"text": text, "t": now}]
        cur.update(answer=text, answer_t=now)
        try:
            Path(f).write_text(json.dumps(cur, indent=1))
        except OSError as e:
            if amend:  # the old answer would keep winning in the file: say so
                return 500, {"code": "write", "error": "The new answer could not be saved (%s); the old one still stands." % e.strerror}
        return 200, {"ok": True, "bead": a["bead"], "next": next_step(a)}

    def file_answer(self, a: Ask, text: str, cwd: str | None, amend: bool = False) -> None:
        """A substantive answer is also filed on the bead where the planner reads it: under `## Testing` for a verify or denied ask,
        `## Decisions` for any other. A bare button answer (right, run again) is not. Best effort: the comment is the answer."""
        plain = text.strip().lower().rstrip(".!") in PLAIN_ANSWERS or text.strip().lower() == "wrong:"
        if plain and not amend:
            return
        head = "## Testing" if a.get("kind") in ("verify", "denied") else "## Decisions"
        question = (a.get("question") or "").strip()
        first = question.splitlines()[0].replace("**", "") if question else a.get("kind", "ask")
        line = "- %s (ask %s) %s -> %s" % (time.strftime("%Y-%m-%d"), a.get("id"), first[:140], " ".join(text.split())[:600])
        try:
            r = subprocess.run(["bd", "show", a["bead"], "--json"], cwd=cwd, capture_output=True, text=True, timeout=30)
            d = json.loads(r.stdout)
            d = d[0] if isinstance(d, list) and d else d
            notes = (d.get("notes") or "").rstrip("\n") if isinstance(d, dict) else ""
            if amend:  # the line this ask filed for the answer it replaces goes
                notes = "\n".join(x for x in notes.split("\n") if "(ask %s) " % a.get("id") not in x)
                if plain:
                    subprocess.run(["bd", "update", a["bead"], "--notes", notes], cwd=cwd, capture_output=True, text=True, timeout=30)
                    return
            i = heading_end(notes, head)
            if i >= 0:
                nxt = notes.find("\n## ", i)
                at = nxt if nxt >= 0 else len(notes)
                notes = notes[:at].rstrip("\n") + "\n" + line + notes[at:]
            else:
                notes = (notes + "\n\n" if notes else "") + head + "\n" + line
            subprocess.run(["bd", "update", a["bead"], "--notes", notes], cwd=cwd, capture_output=True, text=True, timeout=30)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass

    def withdraw(self, body: object) -> Reply:
        """The owner dismisses an ask that no longer applies; the bead is not touched."""
        if not isinstance(body, dict):
            return 400, {"code": "bad_body", "error": "The request was not understood."}
        f, a, problem = self.ask_for(body.get("ask"), withdrawing=True)
        if problem or f is None or a is None:
            return ((200, {"ok": True}) if problem and problem[1].get("code") == "withdrawn" else problem) or (404, {"code": "gone", "error": "This ask no longer exists."})
        why = body.get("why") if isinstance(body.get("why"), str) and body.get("why").strip() else "dismissed by the owner"
        try:  # a run may have used the answer since ask_for looked: withdraw only what is still unused
            cur = json.loads(Path(f).read_text())
        except (OSError, ValueError):
            cur = a
        if cur.get("id") != a.get("id") or cur.get("status") not in OPEN:
            return 409, {"code": "answered", "error": "A run just used this ask; it cannot be withdrawn now."}
        a = cur
        if a.get("answer"):  # an answer no run has used yet goes with the ask, and the record says so
            dropped = a.get("answer")
            a["withdrawn_answer"] = a.pop("answer")
            a.pop("answer_t", None)
            why = "%s (answer dropped: %s)" % (why, " ".join(str(dropped).split())[:120])
            cwd = a.get("repo") or None
            try:  # the bead must not keep it either: a comment says so and the notes line it filed goes
                subprocess.run(["bd", "comments", "add", a["bead"], "Answer to ask %s withdrawn, no run used it: %s" % (
                    a.get("id"), " ".join(str(dropped).split())[:300])], cwd=cwd, capture_output=True, text=True, timeout=30)
                self.file_answer(a, "right", cwd, amend=True)  # a bare answer in amend mode only removes this ask's line from the notes
            except (OSError, subprocess.SubprocessError):
                pass
        a.update(status="withdrawn", withdrawn_why=why[:300], withdrawn=self.env.clock())
        try:
            Path(f).write_text(json.dumps(a, indent=1))
        except OSError as e:
            return 500, {"code": "write", "error": "Could not write the ask file (%s)." % e.strerror}
        return 200, {"ok": True}
