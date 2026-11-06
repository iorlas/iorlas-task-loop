"""The owner-look bead: one per epic, filed after the land with the screenshots, the agent's judgement, the taste items and what no check
could prove."""
import contextlib
import hashlib
from collections.abc import Generator
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from taskloop.adapters import bdcreate, beadtools
from taskloop.adapters.repourl import repo_url
from taskloop.contracts import factorydb, gallery
from taskloop.contracts.ids import BeadId, is_bead_id
from taskloop.contracts.lookrows import LookRaced, LookRows
from taskloop.contracts.ports import BdFailure, BeadPatch, BeadQuery, Git, NewBead
from taskloop.domain.look.matchers import sections

LOOK_LABEL = "owner-look"


class OwnerLook:
    def __init__(self, host: Any, git: Git) -> None:
        self.e = host
        self.git = git

    def look_epic(self) -> str:
        """The bead's epic: parents walked up to the first epic, else the direct parent."""
        e = self.e
        cur, seen = e.bead_parent if is_bead_id(e.bead_parent) else None, set[BeadId]()
        while cur and cur not in seen and len(seen) < 10:
            seen.add(cur)
            d = beadtools.peek(e.store, cur)
            if d and d.issue_type == "epic":
                return str(cur)
            cur = d.parent if d and is_bead_id(d.parent) else None
        return str(e.bead_parent)

    def existing_owner_look(self) -> tuple[str, str]:
        """(id, description) of the owner-look bead to reuse: one already linked (related) to this bead, else the one
        under this bead's epic (tl-bxk.10.28: one review bead per epic, appended to); ('', '') when there is none."""
        e = self.e
        try:
            rows = e.store.find(BeadQuery(label=LOOK_LABEL))
        except BdFailure:
            return "", ""
        epic, by_epic = self.look_epic() or e.bead, ("", "")
        for row in rows:
            d = beadtools.peek(e.store, row.id) or row
            if any(x.id == e.bead for x in d.dependencies):
                return row.id, d.description
            if epic and not by_epic[0] and d.parent == epic and d.status != "closed":
                by_epic = (row.id, d.description)
        return by_epic

    def section(self) -> str:
        """This bead's section of the owner-look bead's body."""
        e = self.e
        parts = [f"## {e.bead}: {e.bead_title}"]
        kept = e.pictures.show_pictures()
        if kept or e.look_unjudged or not e.unverified:
            shots = "\n".join(f"- [{m.name}]({self.link(ref)})" for ref, m in kept) or "(none)"
            judged = " ".join(e.look_notes) or "(the reviewer gave no judgement)"
            unjudged = ("\n" + "\n".join(f"{w} ({u})" for u, w in e.look_unjudged.items()) + "\n") if e.look_unjudged else ""
            parts.append(f"Screenshots of {e.bead} ({e.bead_title}), kept on the dashboard (bead page {e.bead}), not in the repo:\n"
                         f"{shots}\n\nWhat the agent judged: {judged}\n"
                         f"{unjudged}\nNot automatable: the owner reviews the look and feel in a later batch.")
        if e.cases.cases_of("taste"):
            taste = "\n".join("- " + t for t in e.cases.cases_of("taste"))
            parts.append(f"Taste items (the owner decides; they never blocked the land):\n{taste}")
        if e.unverified:
            parts.append(self.unverified_text())
        return "\n".join(parts)

    @staticmethod
    def link(ref: str) -> str:
        """The dashboard's own address of a kept picture (relative to the dashboard: the engine does not know its host)."""
        repo, bead, run, folder, name = ref[len("artifact:"):].split("/", 4)
        stage, _, attempt = folder.rpartition("-")
        return "/api/artifact?" + urlencode({"repo": repo, "bead": bead, "run": run, "stage": stage, "attempt": attempt, "name": name})

    def file_owner_look(self) -> None:
        """After the land: one bead per epic for the owner's later round (look and feel, and what no check could prove),
        filed once and appended to by each later bead of the epic (a re-land replaces its own section)."""
        e = self.e
        if e.look_filed or not (e.pictures.show_pictures() or e.look_unjudged or e.unverified or e.cases.cases_of("taste")):
            return
        section = self.section()
        with self.review_lock():  # list + create/update is one step: three beads of an epic landing together file one bead
            self.file_review(section)

    @contextlib.contextmanager
    def review_lock(self) -> Generator[None]:
        """One filer at a time per (repo, epic), across slots and sessions."""
        e = self.e
        key = f"{repo_url(self.git, str(e.wt))}|{self.look_epic() or e.bead}"
        with e.waits.locked("review_lock", e.home.root / "locks" / f"review-{hashlib.sha1(key.encode()).hexdigest()[:12]}.lock"):
            yield

    def file_review(self, section: str) -> None:
        e = self.e
        head = section.split("\n", 1)[0]
        have, old = self.existing_owner_look()
        made, err = have, ""
        if have:
            kept = [x for x in sections(old) if not x.startswith(head.split(":")[0] + ":")]
            if not beadtools.attempt(e.store.update, have, BeadPatch(description="\n\n".join([*kept, section]))):
                err = "bd refused the update"
        else:
            made, err = bdcreate.create_checked(e.store, NewBead(
                title=("Look review: " if e.pictures.show_pictures() or e.look_unjudged else "Owner review: ") + (e.bead_title or e.bead),
                labels=[LOOK_LABEL], no_inherit_labels=True, description=section, deps=["related:" + e.bead],
                parent=self.look_epic() or e.bead), e.bead, e.log.note)  # no epic: the review bead sits under the bead itself
        if err:
            e.warn(f"owner-look bead {'update' if have else 'create'} failed: {err[:300]}")
            return
        e.look_filed = True
        if e.cases.cases_of("taste"):
            if made and is_bead_id(made):
                self.write_looks(made)
            else:
                e.warn("owner-look bead filed, but its id was not in bd's answer: no looks metadata")

    def write_looks(self, bead_id: BeadId) -> None:
        """tl-bxk.13.15: the gallery's data of the owner-look bead, as its kv row (contracts/lookrows.py; one entry per taste item: id,
        bead, title, note, shots[{path, role before|after, label}], status). A re-land of this bead replaces its own entries and
        keeps one the owner already answered (good or redo). The row is written by compare-and-set, so an answer the owner gives
        meanwhile is not lost, and the bead's metadata (a hold) is not touched."""
        e = self.e
        shots = [{"path": ref, "role": "before" if m.role == "before" else "after", "label": Path(m.name).stem}
                 for ref, m in e.pictures.show_pictures()]
        mine = [{"id": f"{e.bead}#{k}", "bead": e.bead, "title": t, "note": " ".join(e.look_notes)[:600], "shots": shots, "status": "open"}
                for k, t in enumerate(e.cases.cases_of("taste"), 1)]
        shown = beadtools.peek(e.store, bead_id)

        def refile(old: list[gallery.Item]) -> list[gallery.Item]:
            answered = {x.get("id"): x for x in old if x.get("bead") == e.bead and x.get("status") in ("good", "redo")}
            return [x for x in old if x.get("bead") != e.bead] + [answered.get(x["id"], x) for x in mine]

        before = {"metadata": shown.metadata, "description": shown.description} if shown else {}  # a bead from before the row
        try:
            LookRows(e.home).modify(bead_id, lambda: gallery.stored(bead_id, before), refile)
        except (LookRaced, factorydb.DatabaseError) as err:
            e.warn(f"owner-look bead {bead_id}: looks row failed: {err}")

    def unverified_text(self) -> str:
        rows = []
        for u in self.e.unverified:
            source = f", source: {u['source']}" if u.get("source") else ""
            rows.append(f"- {u['what']} ({u['kind']}{source})" + (f": {u['why']}" if u.get("why") else ""))
        return "Unverified, for the owner:\n" + "\n".join(rows)
