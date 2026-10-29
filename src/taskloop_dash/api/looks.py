"""The gallery's endpoints: every look item of a repo with its pictures, and the owner's answers. "good" settles an item; "redo" with a
note files a follow-up bead that carries the note and the pictures; every answer can be taken back (the only writes the gallery
makes, all through the `look` port)."""

import mimetypes
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

from taskloop.contracts import gallery
from taskloop.contracts.dash import Result
from taskloop.contracts.gallery import LABEL, PICTURES
from taskloop_dash.env import Env
from taskloop_dash.readers.beads import Beads, basename
from taskloop_dash.readers.records import Records
from taskloop_dash.views import names

Reply = tuple[int, dict[str, Any]]


class Looks:
    def __init__(self, env: Env, records: Records, beads: Beads) -> None:
        self.env, self.records, self.beads = env, records, beads

    def collect(self, repo: str, beads: list[dict[str, Any]]) -> list[gallery.Item]:
        """Every item of every owner-look bead of the repo (open or closed: an answered item stays so it can be taken back)."""
        out: list[gallery.Item] = []
        for b in beads or []:
            if LABEL not in (b.get("labels") or []):
                continue
            shown = self.beads.show(repo, b["id"]) or {}
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
                sh["url"] = self.shot_url(basename(path), sh["path"])
        return {"repo": basename(path), "items": items, "summary": gallery.summary(items), "repos": repos}

    @staticmethod
    def shot_url(repo: str, path: str) -> str:
        """A picture kept as an artifact ("artifact:<bead>/<name>") is served by /api/artifact, an old repo one by /api/look-shot."""
        if path.startswith("artifact:") and "/" in path:
            bead, name = path[9:].split("/", 1)
            return f"/api/artifact?bead={quote(bead)}&name={quote(name)}"
        return f"/api/look-shot?repo={quote(repo)}&path={quote(path)}"

    def look_shot(self, repo: str, rel: str) -> tuple[bytes, str] | None:
        path, items = self.look_items(repo)
        return self.picture(path, rel, items) if path else None

    @staticmethod
    def picture(repo: str, rel: object, items: list[gallery.Item]) -> tuple[bytes, str] | None:
        """(bytes, content-type) of a picture an item names, or None. The path must be one a looks item lists (never a path of the
        caller's choosing), stay inside the repo, and be a picture, read from disk."""
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
        if not data or data.startswith(b"version https://git-lfs"):  # an LFS pointer is not a picture
            return None
        return data, PICTURES.get(ext) or mimetypes.guess_type(rel)[0] or "application/octet-stream"

    def answer_look(self, body: object) -> Reply:
        """The page's v1 answer: {repo, look_bead, item, verdict good|redo|undo, note}: the same `look` port as /api/v2/look."""
        if not isinstance(body, dict):
            return 400, {"code": "bad_body", "error": "The request was not understood."}
        repo, look_bead, item, verdict = body.get("repo"), body.get("look_bead"), body.get("item"), body.get("verdict")
        note = body.get("note") if isinstance(body.get("note"), str) else ""
        if verdict not in ("good", "redo", "undo") or not names.is_bead_id(look_bead) or not isinstance(item, str):
            return 400, {"code": "bad_body", "error": "The request was not understood."}
        path = self.beads.resolve_repo(str(repo or ""), "")
        if not path:
            return 404, {"code": "repo_missing", "error": "That repo is not registered."}
        done = self.answer(path, item, verdict, note, str(look_bead))
        if not done.ok:
            return 409, {"code": "refused", "error": done.message}
        return 200, {"ok": True, "status": "open" if verdict == "undo" else verdict}

    def answer(self, repo: str, item: str, verdict: str, note: str, look_bead: str = "") -> Result:
        """Answer one look item through the `look` port, then drop what the gallery and the roadmap cached about the repo."""
        done = self.env.ports.look(repo, item, verdict, note, look_bead)
        self.env.ttl.drop("looks:" + repo)
        self.env.ttl.drop("roadmap:" + repo)
        return done
