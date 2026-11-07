"""The owner-look bead: one per epic, filed after the land with the screenshots, the agent's judgement, the taste items and what no check
could prove."""
import contextlib
import hashlib
from collections.abc import Generator
from pathlib import Path
from urllib.parse import urlencode

from tlkernel import factorydb, gallery
from tlkernel.beadsport import BdFailure, BeadPatch, BeadQuery, NewBead
from tlkernel.gitport import Git
from tlkernel.ids import BeadId, is_bead_id
from tlkernel.lookrows import LookRaced, LookRows
from tlkernel.repourl import repo_url
from tlkernel.stagefacts import RunFacts

from taskloop.adapters import bdcreate, beadtools
from taskloop.app.look.host import LookHost, LookPorts
from taskloop.app.look.state import LookState
from taskloop.domain.look.matchers import sections

LOOK_LABEL = "owner-look"


class OwnerLook:
    def __init__(self, facts: RunFacts, ports: LookPorts, state: LookState, hand: LookHost, git: Git) -> None:
        self.facts, self.ports, self.state, self.hand = facts, ports, state, hand
        self.git = git

    def look_epic(self) -> str:
        """The bead's epic: parents walked up to the first epic, else the direct parent."""
        hand, ports = self.hand, self.ports
        cur, seen = hand.bead_parent if is_bead_id(hand.bead_parent) else None, set[BeadId]()
        while cur and cur not in seen and len(seen) < 10:
            seen.add(cur)
            d = beadtools.peek(ports.store, cur)
            if d and d.issue_type == "epic":
                return str(cur)
            cur = d.parent if d and is_bead_id(d.parent) else None
        return str(hand.bead_parent)

    def existing_owner_look(self) -> tuple[str, str]:
        """(id, description) of the owner-look bead to reuse: one already linked (related) to this bead, else the one
        under this bead's epic (tl-bxk.10.28: one review bead per epic, appended to); ('', '') when there is none."""
        facts, ports = self.facts, self.ports
        try:
            rows = ports.store.find(BeadQuery(label=LOOK_LABEL))
        except BdFailure:
            return "", ""
        epic, by_epic = self.look_epic() or facts.bead, ("", "")
        for row in rows:
            d = beadtools.peek(ports.store, row.id) or row
            if any(x.id == facts.bead for x in d.dependencies):
                return row.id, d.description
            if epic and not by_epic[0] and d.parent == epic and d.status != "closed":
                by_epic = (row.id, d.description)
        return by_epic

    def section(self) -> str:
        """This bead's section of the owner-look bead's body."""
        hand, facts, ports, state = self.hand, self.facts, self.ports, self.state
        parts = [f"## {facts.bead}: {hand.bead_title}"]
        kept = ports.pictures.show_pictures()
        if kept or state.unjudged or not hand.review.unverified:
            shots = "\n".join(f"- [{m.name}]({self.link(ref)})" for ref, m in kept) or "(none)"
            judged = " ".join(state.notes) or "(the reviewer gave no judgement)"
            unjudged = ("\n" + "\n".join(f"{w} ({u})" for u, w in state.unjudged.items()) + "\n") if state.unjudged else ""
            parts.append(f"Screenshots of {facts.bead} ({hand.bead_title}), kept on the dashboard (bead page {facts.bead}), "
                         "not in the repo:\n"
                         f"{shots}\n\nWhat the agent judged: {judged}\n"
                         f"{unjudged}\nNot automatable: the owner reviews the look and feel in a later batch.")
        if ports.cases.cases_of("taste"):
            taste = "\n".join("- " + t for t in ports.cases.cases_of("taste"))
            parts.append(f"Taste items (the owner decides; they never blocked the land):\n{taste}")
        if hand.review.unverified:
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
        hand, ports, state = self.hand, self.ports, self.state
        if state.filed or not (ports.pictures.show_pictures() or state.unjudged or hand.review.unverified or ports.cases.cases_of("taste")):
            return
        section = self.section()
        with self.review_lock():  # list + create/update is one step: three beads of an epic landing together file one bead
            self.file_review(section)

    @contextlib.contextmanager
    def review_lock(self) -> Generator[None]:
        """One filer at a time per (repo, epic), across slots and sessions."""
        facts, ports = self.facts, self.ports
        key = f"{repo_url(self.git, facts.wt)}|{self.look_epic() or facts.bead}"
        with ports.waits.locked("review_lock", facts.home.root / "locks" / f"review-{hashlib.sha1(key.encode()).hexdigest()[:12]}.lock"):
            yield

    def file_review(self, section: str) -> None:
        hand, facts, ports, state = self.hand, self.facts, self.ports, self.state
        head = section.split("\n", 1)[0]
        have, old = self.existing_owner_look()
        made, err = have, ""
        if have:
            kept = [x for x in sections(old) if not x.startswith(head.split(":")[0] + ":")]
            if not beadtools.attempt(ports.store.update, BeadId(have), BeadPatch(description="\n\n".join([*kept, section]))):
                err = "bd refused the update"
        else:
            made, err = bdcreate.create_checked(ports.store, NewBead(
                title=("Look review: " if ports.pictures.show_pictures() or state.unjudged else "Owner review: ")
                + (hand.bead_title or facts.bead),
                labels=[LOOK_LABEL], no_inherit_labels=True, description=section, deps=["related:" + facts.bead],
                parent=self.look_epic() or facts.bead), facts.bead, ports.log.note)  # no epic: the review bead sits under the bead itself
        if err:
            ports.warn(f"owner-look bead {'update' if have else 'create'} failed: {err[:300]}")
            return
        state.filed = True
        if ports.cases.cases_of("taste"):
            if made and is_bead_id(made):
                self.write_looks(made)
            else:
                ports.warn("owner-look bead filed, but its id was not in bd's answer: no looks metadata")

    def write_looks(self, bead_id: BeadId) -> None:
        """tl-bxk.13.15: the gallery's data of the owner-look bead, as its look_doc row (tlkernel/lookrows.py; one entry per taste item: id,
        bead, title, note, shots[{path, role before|after, label}], status). A re-land of this bead replaces its own entries and
        keeps one the owner already answered (good or redo). The row is written by compare-and-set, so an answer the owner gives
        meanwhile is not lost, and the bead's metadata (a hold) is not touched."""
        facts, ports, state = self.facts, self.ports, self.state
        shots = [{"path": ref, "role": "before" if m.role == "before" else "after", "label": Path(m.name).stem}
                 for ref, m in ports.pictures.show_pictures()]
        mine = [{"id": f"{facts.bead}#{k}", "bead": facts.bead, "title": t, "note": " ".join(state.notes)[:600], "shots": shots,
                 "status": "open"}
                for k, t in enumerate(ports.cases.cases_of("taste"), 1)]
        shown = beadtools.peek(ports.store, bead_id)

        def refile(old: list[gallery.Item]) -> list[gallery.Item]:
            answered = {x.get("id"): x for x in old if x.get("bead") == facts.bead and x.get("status") in ("good", "redo")}
            return [x for x in old if x.get("bead") != facts.bead] + [answered.get(x["id"], x) for x in mine]

        before = {"metadata": shown.metadata, "description": shown.description} if shown else {}  # a bead from before the row
        try:
            LookRows(facts.home).modify(bead_id, lambda: gallery.stored(bead_id, before), refile)
        except (LookRaced, factorydb.DatabaseError) as err:
            ports.warn(f"owner-look bead {bead_id}: looks row failed: {err}")

    def unverified_text(self) -> str:
        rows = []
        for u in self.hand.review.unverified:
            source = f", source: {u['source']}" if u.get("source") else ""
            rows.append(f"- {u['what']} ({u['kind']}{source})" + (f": {u['why']}" if u.get("why") else ""))
        return "Unverified, for the owner:\n" + "\n".join(rows)
