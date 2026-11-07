"""Asks and transition receipts have one atomic authority in factory.db."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
import support.paths  # noqa: F401
from support.askjson import unreadable_ask

from contracts import samples as S
from tlkernel import factorydb, wire
from tlkernel.ask import Ask, AskAnswer
from tlkernel.askenums import AskStatus
from tlkernel.askrows import AskRows, DbLedger, read_snapshot
from tlkernel.askstore import AskStore
from tlkernel.dash import OwnerCause, Stick
from tlkernel.docstore import Absent, ForeignVersion, JsonStore, Present, Torn
from tlkernel.ledger import LedgerEntry
from tlkernel.paths import ConfigDir
from tlkernel.wire import Refused
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory


def unexpected_access(*_args, **_kwargs):
    raise AssertionError("unexpected storage access")


class AskRowsTest(Case):
    def setup_method(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(factorydb.close_shared)
        self.cfg = ConfigDir(Path(tmp.name))
        self.store = AskStore.at(self.cfg)
        self.ask = S.ASK.replace(status=AskStatus.OPEN, answer=None, answered=None, consumed=None)
        self.rows = AskRows(self.cfg)

    def connection(self):
        return self.rows.connection()

    def test_roundtrip_relational_columns_and_revisions(self):
        doc = self.store.of(self.ask.bead)
        assert doc.read() == Absent()
        for rev, rec in enumerate((self.ask, self.ask.replace(repo="/new", status=AskStatus.ANSWERED, consumed=23.0))):
            doc.write(rec)
            assert (doc.get(), doc.need(), doc.read()) == (rec, rec, Present(rec))
            row = self.connection().execute("SELECT bead,id,repo,status,t,consumed,body,rev FROM ask").fetchone()
            assert row[:6] == (rec.bead, rec.id, rec.repo, rec.status.value, rec.t, rec.consumed)
            assert json.loads(row[6]) == wire.dump(rec)
            assert row[7] == rev
        assert self.store.docs.keys() == [self.ask.bead]
        doc.delete()
        assert (doc.read(), self.store.docs.keys()) == (Absent(), [])

    @pytest.mark.parametrize("body", (
        '{"v": 3, "id": "tl-7-1", "bead"', '[]', '{}', 'null',
        '{"v": 1, "id": "tl-7-2", "bead": "tl-7", "status": "open", "kind": "verify"}',
        {"v": 99}, {"status": "alien"},
    ))
    def test_classification_uses_the_same_decoder_as_files(self, body):
        path = self.cfg.root / "classification.json"
        file = JsonStore(path, Ask)
        if isinstance(body, dict):
            body = json.dumps(wire.dump(self.ask) | body)
        path.write_text(body)
        unreadable_ask(self.cfg, self.ask.bead, body)
        expected = file.read()
        actual = self.store.of(self.ask.bead).read()
        assert type(actual) is type(expected)
        if isinstance(expected, Torn):
            assert isinstance(actual, Torn)
            assert actual.why == expected.why
            with pytest.raises(Refused):
                self.store.get(self.ask.bead)
        else:
            assert isinstance(actual, ForeignVersion) and isinstance(expected, ForeignVersion)
            assert (actual.found, actual.want) == (expected.found, expected.want)
            assert self.store.orphans() == [self.ask.bead]

    def test_two_answers_have_one_winner_and_two_attempt_receipts(self):
        self.store.file(self.ask)
        ready = Barrier(2)

        def answer(text):
            store = AskStore.at(self.cfg)
            ready.wait(timeout=30)
            return store.answer(self.ask.bead, self.ask.id, AskAnswer(action="text", text=text, t=10.0))

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(answer, text) for text in ("A", "B")]
            results = [future.result(timeout=10) for future in futures]
        assert sorted(why for _, why in results) == ["", "answered"]
        winner = next(rec for rec, why in results if not why)
        assert self.store.get(self.ask.bead) == winner
        receipts = self.store.rows()[1:]
        assert [row.event for row in receipts] == ["answer", "answer_refused"]
        assert {row.answer for row in receipts} == {"A", "B"}
        assert receipts[-1].why == "answered"
        assert self.connection().execute("SELECT rev FROM ask").fetchone()[0] == 1

    def test_ledger_failure_rolls_back_the_document_and_revision(self, monkeypatch):
        self.store.file(self.ask)
        answer = AskAnswer(action="text", text="A")
        transitions = (
            lambda: self.store.file(self.ask.replace(decision="new")),
            lambda: self.store.answer(self.ask.bead, self.ask.id, answer),
            lambda: self.store.amend(self.ask.bead, self.ask.id, answer),
            lambda: self.store.consume(self.ask.bead, 1.0, unanswered=True),
            lambda: self.store.withdraw(self.ask.bead, self.ask.id, "obsolete", 1.0),
            lambda: self.store.close(self.ask.bead, self.ask.id, "closed"),
            lambda: self.store.correct_cause(self.ask.bead, self.ask.id, OwnerCause.REQUIREMENT, 1.0),
            lambda: self.store.stuck(self.ask.bead, self.ask.id, Stick.ONCE, "", 1.0))

        def receipt_failed(*_args, **_kwargs):
            raise ValueError("receipt failed")

        for transition in transitions:
            with monkeypatch.context() as patch:
                patch.setattr(DbLedger, "append", receipt_failed)
                with pytest.raises(ValueError, match="receipt failed"):
                    transition()
            assert self.store.get(self.ask.bead) == self.ask
            assert [row.event for row in self.store.rows()] == ["raise"]
            assert self.connection().execute("SELECT rev FROM ask").fetchone()[0] == 0

    def test_refused_attempt_does_not_become_the_answer_on_later_rows(self):
        self.store.file(self.ask)
        self.store.answer(self.ask.bead, self.ask.id, AskAnswer(action="text", text="winner"))
        self.store.answer(self.ask.bead, self.ask.id, AskAnswer(action="text", text="loser"))
        self.store.correct_cause(self.ask.bead, self.ask.id, OwnerCause.REQUIREMENT, 2.0)
        assert self.store.rows()[-1].answer == "winner"
        assert self.store.rows()[-2].answer == "loser"

    def test_answer_amend_consume_withdraw_and_annotations(self):
        self.store.file(self.ask)
        for method, text in ((self.store.answer, "first"), (self.store.amend, "amended")):
            rec, why = method(self.ask.bead, self.ask.id, AskAnswer(action="text", text=text, t=10.0))
            assert why == ""
            assert rec is not None and rec.answer is not None
            assert rec.answer.text == text
        assert self.store.correct_cause(self.ask.bead, self.ask.id, OwnerCause.REQUIREMENT, 11.0)
        assert self.store.stuck(self.ask.bead, self.ask.id, Stick.ONCE, "ref", 12.0)
        consumed = self.store.consume(self.ask.bead, 13.0)
        assert consumed is not None
        assert consumed.consumed == 13.0
        assert self.store.withdraw(self.ask.bead, self.ask.id, "late", 14.0)[1] == "consumed"
        assert [r.event for r in self.store.rows()] == ["raise", "answer", "answer", "cause", "stick", "consume"]
        self.store.file(self.ask.replace(id="next"))
        assert self.store.withdraw(self.ask.bead, "next", "obsolete", 15.0)[1] == ""
        assert self.store.rows()[-1].event == "withdraw"

    def test_ledger_origin_uniqueness_and_cursors(self):
        ledger = DbLedger(self.rows)
        rec = LedgerEntry(t=1.0, event="raise", ask=self.ask.id, bead=self.ask.bead)
        with self.rows.transaction():
            first = ledger.insert(rec, "same-origin")
            assert first > 0
            assert ledger.insert(rec, "same-origin") == 0
        second = ledger.append(rec.replace(event="answer"))
        assert second == first  # append returns the start cursor, read_from resumes after that cursor
        page = ledger.read_from(0, limit=1)
        assert (len(page.items), page.cursor) == (1, first)
        assert [i.rec.event for i in ledger.read_from(page.cursor).items] == ["answer"]
        assert [i.rec.event for i in ledger.tail(1).items] == ["answer"]
        assert [i.rec.event for i in ledger.tail(1, before=first).items] == ["raise"]

    def test_a_miss_is_none_and_a_broken_db_is_an_error(self):
        assert self.store.get(self.ask.bead) is None
        assert self.store.rows() == []
        factorydb.close_shared()
        self.cfg.factory_db().write_bytes(b"broken database")
        for read in (self.store.all, self.store.rows, lambda: read_snapshot(self.cfg)):
            with pytest.raises(factorydb.DatabaseError):
                read()

    def test_dashboard_uses_readonly_open_and_never_creates_missing_db(self, monkeypatch):
        with pytest.raises(factorydb.DatabaseError):
            read_snapshot(self.cfg)
        assert not self.cfg.factory_db().exists()
        self.store.file(self.ask)
        with monkeypatch.context() as patch:
            patch.setattr(factorydb, "shared_rw", unexpected_access)
            asks, ledger = read_snapshot(self.cfg)
        assert asks == [self.ask]
        assert [row.event for row in ledger] == ["raise"]
