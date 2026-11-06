"""The dashboard's existing run event feed names checks executed in the slot."""

from support.case import Case
from support.memstores import fake_stores

from taskloop.app.checks.checklog import CheckLog
from taskloop.contracts import log
from taskloop.contracts.checks import Check
from taskloop.contracts.ids import CheckId
from taskloop.contracts.runlife import Liveness
from taskloop.stores.runlog import RunLog
from taskloop_dash.views import live_events, live_lines


class SlotCheckLocation(Case):
    def test_slot_execution_location_reaches_dashboard_lines_through_run_records(self):
        stores = fake_stores()
        doc = stores.run_log("slot-gate")
        checks = CheckLog(RunLog(doc, run_id="slot-gate", host="host"))
        checks.start(Check(id=CheckId("unity"), cmd="unity-check", run_in="slot"), 1)
        rows = doc.read_from().items
        events = [live_events.engine_event(row.rec, n) for n, row in enumerate(rows)]
        page = live_lines.page(events, "", Liveness.LIVE)
        assert "check unity: execution in slot" in [line.text for line in page.lines]
        assert any(isinstance(row.rec, log.CheckStart) for row in rows)
