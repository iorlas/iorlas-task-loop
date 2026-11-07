"""The line for a slot as `lease` rows (kind `slot`, name `<repo_key>/<seq>`, the Ticket in `body`) in factory.db. A new ticket's number is
taken in one write transaction, past every live row and the repo's `ticket_doc` counter, so two waiters never share one and a number never
repeats across an empty line."""
import json
import time

from tlkernel import wire
from tlkernel.docrows import TICKET_DOCS
from tlkernel.locks import Ticket
from tlkernel.looprows import LoopRows
from tlkernel.paths import ConfigDir

KIND = "slot"


def name_of(repo_key: str, seq: int) -> str:
    return f"{repo_key}/{seq:012d}"


def span(repo_key: str) -> tuple[str, str]:
    """The names of one repo's tickets, as a range ('0' is the character after '/')."""
    return f"{repo_key}/", f"{repo_key}0"


class TicketRows:
    def __init__(self, cfg: ConfigDir) -> None:
        self.cfg, self.rows = cfg, LoopRows(cfg, "")

    def take(self, repo_key: str, why: str, prio: int, *, pid: int, now: float, pid_start: float | None = None, bead: str = "") -> Ticket:
        counter = f"slot-seq:{repo_key}"
        with self.rows.transaction() as con:
            last = con.execute(f"SELECT v FROM {TICKET_DOCS} WHERE k=?", (counter,)).fetchone()
            live = con.execute("SELECT name FROM lease WHERE kind=? AND name >= ? AND name < ?", (KIND, *span(repo_key))).fetchall()
            seq = max([int(last[0]) if last else 0, *(int(n[0].rsplit("/", 1)[1]) for n in live)]) + 1
            ticket = Ticket(pid=pid, why=why, since=now, prio=prio, seq=seq, pid_start=pid_start, bead=bead)
            con.execute("INSERT INTO lease (kind, name, holder, pid, start_id, since, body) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (KIND, name_of(repo_key, seq), why, pid, None if pid_start is None else str(pid_start), now,
                         json.dumps(wire.dump(ticket))))
            con.execute(f"INSERT INTO {TICKET_DOCS} (k, v, t) VALUES (?, ?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v, t=excluded.t",
                        (counter, str(seq), time.time()))
        return ticket

    def line(self, repo_key: str) -> list[Ticket]:
        out: list[Ticket] = []
        for _, body in self.rows.select("SELECT name, body FROM lease WHERE kind=? AND name >= ? AND name < ?",
                                           (KIND, *span(repo_key))):
            try:
                ticket = wire.load(Ticket, json.loads(body))
            except (ValueError, TypeError):
                continue
            if ticket.alive():
                out.append(ticket)
            else:
                self.drop(repo_key, ticket.seq)
        return sorted(out, key=lambda t: (t.prio, t.seq))

    def drop(self, repo_key: str, seq: int) -> None:
        with self.rows.transaction() as con:
            con.execute("DELETE FROM lease WHERE kind=? AND name=?", (KIND, name_of(repo_key, seq)))
