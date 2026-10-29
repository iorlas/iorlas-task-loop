"""Look items: every item of a repo's owner-look beads with its pictures (GET /api/look-shot serves one), and the owner's answer through
the `look` port. "good" settles an item; "redo" with a note files a follow-up bead that carries the note and the pictures."""

import mimetypes
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

from taskloop.contracts import gallery
from taskloop.contracts.dash import Result
from taskloop.contracts.gallery import LABEL, PICTURES
from taskloop_dash.env import Env
from taskloop_dash.readers.beads import Beads
from taskloop_dash.readers.records import Records


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

    def answer(self, repo: str, item: str, verdict: str, note: str, look_bead: str = "") -> Result:
        """Answer one look item through the `look` port, then drop the repo's cached items."""
        done = self.env.ports.look(repo, item, verdict, note, look_bead)
        self.env.ttl.drop("looks:" + repo)
        return done
