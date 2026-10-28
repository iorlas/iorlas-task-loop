"""The gallery's endpoints: every look item of a repo with its pictures, and the owner's answers. "good" settles an item; "redo" with a
note files a follow-up bead that carries the note and the pictures; every answer can be taken back (the only writes the gallery
makes, all through bd)."""

import json
import mimetypes
import os
import subprocess
import threading
from pathlib import Path
from typing import Any
from urllib.parse import quote

from taskloop_dash.env import Env
from taskloop_dash.readers.beads import Beads, basename
from taskloop_dash.readers.records import Records
from taskloop_dash.views import gallery, names
from taskloop_dash.views.gallery import LABEL, PICTURES

REFS = ("HEAD", "origin/main", "main", "master")  # where a landed picture may be read when the checkout moved on
NOTE_MAX = 2000
Reply = tuple[int, dict[str, Any]]


def bd_json(bd: Any, repo: str, *args: str) -> Any:
    try:
        r = bd(repo, *args)
        out = json.loads(r.stdout) if r.returncode == 0 else None
    except (subprocess.SubprocessError, ValueError, OSError):
        return None
    return out[0] if isinstance(out, list) and out and args[0] == "show" else out


def last_line(r: "subprocess.CompletedProcess[str]", empty: str = "") -> str:
    return ((r.stderr or r.stdout or "").strip().splitlines() or [empty])[-1][:200]


class Looks:
    def __init__(self, env: Env, records: Records, beads: Beads) -> None:
        self.env, self.records, self.beads = env, records, beads
        self.answering = threading.Lock()  # one answer at a time: two clicks never file two follow-ups

    def collect(self, repo: str, beads: list[dict[str, Any]]) -> list[gallery.Item]:
        """Every item of every owner-look bead of the repo (open or closed: an answered item stays so it can be taken back)."""
        out: list[gallery.Item] = []
        for b in beads or []:
            if LABEL not in (b.get("labels") or []):
                continue
            shown = bd_json(self.env.ports.bd, repo, "show", b["id"]) or {}
            filed = gallery.epoch(b.get("created_at") or shown.get("created_at"))
            out += [dict(i, filed=filed) for i in gallery.items_of(b["id"], dict(shown, title=shown.get("title") or b.get("title")))]
        return out

    def look_items(self, repo: str) -> tuple[str, list[gallery.Item]]:
        """Items of the repo's owner-look beads, cached 10 s."""
        path = (self.beads.resolve_repo(repo, "") if repo else (self.records.repos() or [""])[0]) or ""
        if not path:
            return "", []
        return path, self.env.ttl.get("looks:" + path, 10, lambda: self.collect(path, self.beads.beads_of(path)))

    def api_looks(self, repo: str = "") -> dict[str, Any]:
        """The gallery: every look item of the repo, open ones first (newest bead last), with counts."""
        self.env.touch()
        path, items = self.look_items(repo)
        repos = [basename(p) for p in self.records.repos()]
        if not path:
            return {"repo": repo, "items": [], "summary": {"open": 0, "good": 0, "redo": 0}, "repos": repos}
        order = {"open": 0, "redo": 1, "good": 2}
        items = sorted(items, key=lambda i: (order[i["status"]], -(i["answered"] or 0)))
        for i in items:
            for sh in i["shots"]:
                sh["url"] = "/api/look-shot?repo=%s&path=%s" % (quote(basename(path)), quote(sh["path"]))
        return {"repo": basename(path), "items": items, "summary": gallery.summary(items), "repos": repos}

    def look_shot(self, repo: str, rel: str) -> tuple[bytes, str] | None:
        path, items = self.look_items(repo)
        return self.picture(path, rel, items) if path else None

    @staticmethod
    def picture(repo: str, rel: object, items: list[gallery.Item]) -> tuple[bytes, str] | None:
        """(bytes, content-type) of a picture an item names, or None. The path must be one a looks item lists (never a path of the
        caller's choosing), stay inside the repo, and be a picture: disk first, then the base branch's copy."""
        rel = str(rel or "").replace("\\", "/")
        ext = os.path.splitext(rel)[1].lower()
        if ext not in PICTURES or not any(s["path"] == rel for i in items for s in i["shots"]):
            return None
        root = os.path.realpath(repo)
        f = os.path.realpath(os.path.join(root, rel))
        data = None
        if f.startswith(root + os.sep) and os.path.isfile(f):
            try:
                data = Path(f).read_bytes()
            except OSError:
                data = None
        if data is None:
            for ref in REFS:
                try:
                    r = subprocess.run(["git", "show", "%s:%s" % (ref, rel)], cwd=repo, capture_output=True, timeout=20)
                except (subprocess.SubprocessError, OSError):
                    return None
                if r.returncode == 0:
                    data = r.stdout
                    break
        if not data or data.startswith(b"version https://git-lfs"):  # an LFS pointer is not a picture
            return None
        return data, PICTURES.get(ext) or mimetypes.guess_type(rel)[0] or "application/octet-stream"

    def answer_look(self, body: object) -> Reply:
        repo = body.get("repo") if isinstance(body, dict) and isinstance(body.get("repo"), str) else ""
        path = self.beads.resolve_repo(str(repo), "")
        if not path:
            return 404, {"code": "repo_missing", "error": "That repo is not registered."}
        code, out = self.answer(path, body)
        self.env.ttl.drop("looks:" + path)
        self.env.ttl.drop("roadmap:" + path)
        return code, out

    def answer(self, repo: str, body: object, now: float | None = None) -> Reply:
        """body: {look_bead, item, verdict good|redo|undo, note}. good: the item is settled, and the look bead closes when no item
        waits. redo: a follow-up bead carries the note and the pictures. undo: back to open. One answer per item."""
        now = now or self.env.clock()
        if not isinstance(body, dict):
            return 400, {"code": "bad_body", "error": "The request was not understood."}
        look_bead, item_id, verdict = body.get("look_bead"), body.get("item"), body.get("verdict")
        note = body.get("note") if isinstance(body.get("note"), str) else ""
        note = note.strip()[:NOTE_MAX]
        if verdict not in ("good", "redo", "undo") or not names.is_bead_id(look_bead) or not isinstance(item_id, str):
            return 400, {"code": "bad_body", "error": "The request was not understood."}
        if verdict == "redo" and not note:
            return 400, {"code": "empty", "error": "Write what to change first."}
        with self.answering:
            return self._answer(repo, str(look_bead), item_id, str(verdict), note, now)

    def _answer(self, repo: str, look_bead: str, item_id: str, verdict: str, note: str, now: float) -> Reply:
        try:
            return self._apply(repo, look_bead, item_id, verdict, note, now)
        except OSError as err:
            return 502, {"code": "no_bd", "error": "The dashboard cannot run bd (%s). Nothing was changed." % err}
        except subprocess.SubprocessError as err:
            return 502, {"code": "bd", "error": "bd did not answer (%s)." % type(err).__name__}

    def _apply(self, repo: str, look_bead: str, item_id: str, verdict: str, note: str, now: float) -> Reply:
        shown = bd_json(self.env.ports.bd, repo, "show", look_bead)
        if not shown or LABEL not in (shown.get("labels") or []):
            return 404, {"code": "bead_missing", "error": "The look bead %s no longer exists." % look_bead}
        e = next((x for x in gallery.stored(look_bead, shown) if x.get("id") == item_id), None)
        if e is None:
            return 404, {"code": "item_missing", "error": "That item is gone. Reload the page."}
        state = e.get("status") if e.get("status") in ("good", "redo") else "open"
        if verdict == "undo" and state == "open":
            return 200, {"ok": True, "status": "open"}
        if verdict != "undo" and state != "open":
            return 409, {"code": "answered", "error": "Already answered (%s). Take that back first." % state, "status": state}
        made = ""
        if verdict == "redo":  # before the fresh read below: the engine may have written `looks` meanwhile
            ok, made = self.file_redo(repo, look_bead, e, note)
            if not ok:
                return 502, {"code": "bd", "error": "bd refused the follow-up bead: %s" % made}
        shown = bd_json(self.env.ports.bd, repo, "show", look_bead) or shown
        items = gallery.stored(look_bead, shown)
        e = next((x for x in items if x.get("id") == item_id), None)
        if e is None:
            self.drop(repo, made)
            return 404, {"code": "item_missing", "error": "That item is gone. Reload the page."}
        old_redo = e.get("redo_bead") or ""
        if verdict == "undo":
            e.update(status="open", redo_bead="", answer_note="", answered=0)
        elif verdict == "good":
            e.update(status="good", answer_note=note, answered=now)
        else:
            e.update(status="redo", redo_bead=made, answer_note=note, answered=now)
        ok, why = self.save(repo, look_bead, shown, items)
        if not ok:
            self.drop(repo, made)
            return 502, {"code": "bd", "error": "bd refused the answer: %s" % why}
        if verdict == "undo":
            self.drop(repo, old_redo, "the owner took the redo back")
        waiting = sum(1 for x in items if x.get("status") not in ("good", "redo"))
        if verdict == "undo" and shown.get("status") == "closed":
            self.env.ports.bd(repo, "update", look_bead, "--status", "open")
        elif verdict != "undo" and not waiting:
            self.env.ports.bd(repo, "close", look_bead, "--reason", "the owner answered every look")
        return 200, {"ok": True, "status": e["status"], "redo_bead": e.get("redo_bead") or "", "open": waiting}

    def save(self, repo: str, look_bead: str, shown: dict[str, Any], items_meta: list[dict[str, Any]]) -> tuple[bool, str]:
        meta = dict(shown.get("metadata") or {})
        meta["looks"] = items_meta
        r = self.env.ports.bd(repo, "update", look_bead, "--metadata", json.dumps(meta))
        return r.returncode == 0, last_line(r)

    def drop(self, repo: str, bead: str, why: str = "the answer could not be saved") -> None:
        """Close a follow-up bead that no answer points at (a failed save, an undone redo)."""
        if bead and names.is_bead_id(bead):
            self.env.ports.bd(repo, "close", bead, "--reason", why)

    def file_redo(self, repo: str, look_bead: str, e: dict[str, Any], note: str) -> tuple[bool, str]:
        """The follow-up bead of a redo: the owner's note and the pictures, related to the bead the look came from."""
        pics = "\n".join("- %s (%s)" % (s["path"], s.get("role") or "after") for s in e.get("shots") or [])
        desc = "The owner looked at \"%s\" (%s) and asked for a change.\n\nWhat to change:\n%s\n\nPictures:\n%s\n" % (
            e.get("title") or e.get("id"), e.get("bead") or look_bead, note, pics or "(none)")
        args = ["create", "Redo look: " + (e.get("title") or e.get("id") or look_bead)[:90], "--type", "task", "--priority", "2",
                "--description", desc, "--deps", "related:" + (e.get("bead") or look_bead)]
        r = self.env.ports.bd(repo, *args)
        if r.returncode != 0:
            return False, last_line(r, "no output")
        try:
            out = json.loads(r.stdout or "{}")
            out = out[0] if isinstance(out, list) and out else out
            made = str(out.get("id") or "")
        except (ValueError, AttributeError):
            made = ""
        if not made:
            return False, "bd's answer had no id"
        self.env.ports.bd(repo, "update", made, "--metadata", json.dumps({"looks": {"from": e.get("id"), "shots": e.get("shots") or [], "note": note}}))
        return True, made
