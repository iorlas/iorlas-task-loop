"""The owner-look bead: one per epic, filed after the land with the screenshots, the agent's judgement, the taste items and what no check
could prove."""
import contextlib
import hashlib
from collections.abc import Generator
from pathlib import Path
from typing import Any
from urllib.parse import quote

from taskloop.adapters import bdcreate, beadtools, ident
from taskloop.contracts.ids import BeadId, is_bead_id
from taskloop.contracts.ports import BdFailure, BeadPatch, BeadQuery, NewBead
from taskloop.domain.look.matchers import sections

LOOK_LABEL = "owner-look"


class OwnerLook:
    def __init__(self, host: Any) -> None:
        self.e = host

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
        if e.look_paths or e.look_unjudged or not e.unverified:
            shots = "\n".join(f"- [{n}]({self.link(n)})" for n in e.look_paths) or "(none)"
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

    def link(self, name: str) -> str:
        """The dashboard's own address of a kept picture (relative to the dashboard: the engine does not know its host)."""
        return f"/api/artifact?bead={quote(self.e.bead)}&name={quote(name)}"

    def file_owner_look(self) -> None:
        """After the land: one bead per epic for the owner's later round (look and feel, and what no check could prove),
        filed once and appended to by each later bead of the epic (a re-land replaces its own section)."""
        e = self.e
        if e.look_filed or not (e.look_paths or e.look_unjudged or e.unverified or e.cases.cases_of("taste")):
            return
        section = self.section()
        with self.review_lock():  # list + create/update is one step: three beads of an epic landing together file one bead
            self.file_review(section)

    @contextlib.contextmanager
    def review_lock(self) -> Generator[None]:
        """One filer at a time per (repo, epic), across slots and sessions."""
        e = self.e
        key = f"{e.git('remote', 'get-url', 'origin') or str(e.wt)}|{self.look_epic() or e.bead}"
        with e.waits.locked("review_lock", ident.config_dir() / "locks" / f"review-{hashlib.sha1(key.encode()).hexdigest()[:12]}.lock"):
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
                title=("Look review: " if e.look_paths or e.look_unjudged else "Owner review: ") + (e.bead_title or e.bead),
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
        """tl-bxk.13.15: the gallery's data on the owner-look bead, as metadata `looks` (one entry per taste item: id, bead,
        title, note, shots[{path, role before|after, label}], status). A re-land of this bead replaces its own entries and
        keeps one the owner already answered (good or redo)."""
        e = self.e
        shots: list[dict[str, str]] = []
        for n in e.look_paths:
            b = e.pictures.before_shot(n)
            if b:
                shots.append({"path": f"artifact:{b.parent.name}/{b.name}", "role": "before", "label": Path(n).stem})
            shots.append({"path": f"artifact:{e.bead}/{n}", "role": "after", "label": Path(n).stem})
        mine = [{"id": f"{e.bead}#{k}", "bead": e.bead, "title": t, "note": " ".join(e.look_notes)[:600], "shots": shots, "status": "open"}
                for k, t in enumerate(e.cases.cases_of("taste"), 1)]
        shown = beadtools.peek(e.store, bead_id)
        meta = dict(shown.metadata) if shown else {}
        old = meta.get("looks") if isinstance(meta.get("looks"), list) else []
        answered = {x.get("id"): x for x in old if isinstance(x, dict) and x.get("bead") == e.bead and x.get("status") in ("good", "redo")}
        meta["looks"] = [x for x in old if isinstance(x, dict) and x.get("bead") != e.bead] + [answered.get(x["id"], x) for x in mine]
        if not beadtools.attempt(e.store.update, bead_id, BeadPatch(metadata=meta)):
            e.warn(f"owner-look bead {bead_id}: looks metadata failed")

    def unverified_text(self) -> str:
        rows = []
        for u in self.e.unverified:
            source = f", source: {u['source']}" if u.get("source") else ""
            rows.append(f"- {u['what']} ({u['kind']}{source})" + (f": {u['why']}" if u.get("why") else ""))
        return "Unverified, for the owner:\n" + "\n".join(rows)
