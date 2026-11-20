"""The agent_stop table's sole reader/writer. Each callback commits one short fenced transaction."""

from taskloop.agents.stop_models import AgentStop, StopPhase, StopProof, decode, encode
from taskloop.attempt_reads import StoreConnection, StoreRefused, StoreUnavailable, as_text
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey


def stored(data: object) -> AgentStop:
    try:
        return decode(as_text(data))
    except ValueError as error:
        raise StoreUnavailable("Malformed stored agent stop") from error


class StopStore(StoreConnection):
    def get(self, attempt_id: str) -> AgentStop | None:
        with self._connection() as con:
            row = con.execute("SELECT data FROM agent_stop WHERE attempt_id=?", (attempt_id,)).fetchone()
        return None if row is None else stored(row[0])

    def _fence(self, record: AgentStop, attempts: AttemptStore, *, captured: bool = False) -> None:
        key = AttemptKey(record.attempt_id, record.dispatch_token, record.generation)
        found = attempts.load(key)
        entry, agent = record.entry, record.agent
        if (found is None or found.admission.entry != (entry.pid, entry.start, entry.boot)
                or found.worker is None or found.phase not in (("registered", "captured") if captured else ("registered",))):
            raise StoreRefused("worker_mismatch")
        worker = found.worker
        if (worker.pid, worker.pgid, worker.start, worker.boot) != (agent.pid, agent.pgid, agent.start, agent.boot):
            raise StoreRefused("worker_mismatch")

    def request(self, record: AgentStop) -> AgentStop:
        with self._connection(write=True) as con:
            self._fence(record, AttemptStore(lambda: con))
            con.execute("INSERT INTO agent_stop (attempt_id,data) VALUES (?,?) ON CONFLICT DO NOTHING",
                        (record.attempt_id, encode(record)))
            row = con.execute("SELECT data FROM agent_stop WHERE attempt_id=?", (record.attempt_id,)).fetchone()
            found = None if row is None else stored(row[0])
            if found != record:
                raise StoreRefused("changed")
        return record

    def report(self, intent: AgentStop, proof: StopProof, now: float) -> AgentStop:
        result = AgentStop.model_validate({**intent.model_dump(), "phase": StopPhase.REPORTED, "reported_at": now, "proof": proof})
        with self._connection(write=True) as con:
            self._fence(intent, AttemptStore(lambda: con))
            row = con.execute("SELECT data FROM agent_stop WHERE attempt_id=?", (intent.attempt_id,)).fetchone()
            found = None if row is None else stored(row[0])
            if found != result:
                if found != intent:
                    raise StoreRefused("changed")
                con.execute("UPDATE agent_stop SET data=? WHERE attempt_id=?", (encode(result), intent.attempt_id))
        return result

    def observed_gone(self, previous: AgentStop, now: float) -> None:
        """Adopt an observed completed effect, without inventing signal delivery or issuing another stop."""
        if previous.phase == StopPhase.OBSERVED_GONE:
            return
        result = AgentStop.model_validate({**previous.model_dump(), "phase": StopPhase.OBSERVED_GONE, "observed_gone_at": now})
        with self._connection(write=True) as con:
            self._fence(previous, AttemptStore(lambda: con), captured=True)
            changed = con.execute("UPDATE agent_stop SET data=? WHERE attempt_id=? AND data=?",
                                  (encode(result), previous.attempt_id, encode(previous))).rowcount
            if changed != 1:
                raise StoreRefused("changed")
