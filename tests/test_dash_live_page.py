"""The bead page (static/live.html), checked headless: no browser here, so string asserts on the page and the feed it reads."""

import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import support.paths  # noqa: E402, F401
from test_dash_live import make_run, put  # noqa: E402

from taskloop_dash.api import live  # noqa: E402

PAGE = (ROOT / "src" / "taskloop_dash" / "static" / "live.html").read_text(encoding="utf-8")
CSS = PAGE.split("<style>")[1].split("</style>")[0]


class Feed(unittest.TestCase):
    def test_feed_carries_what_the_page_renders(self):
        with tempfile.TemporaryDirectory() as d:
            log, lf = make_run(d)
            put(lf, [{"t": 1793000009.0, "k": "cmd_end", "id": "1", "exit": 1, "out": "boom", "secs": 2.0}])
            run = live.LiveRun(log)
            run.refresh()
            ev = {(e["src"], e["k"]): e for e in live.page(run)["events"]}
            self.assertIn("t", ev[("engine", "cmd_start")])  # the open row's data-t0
            self.assertEqual(ev[("engine", "cmd_end")]["exit"], 0)
            self.assertIn("secs", ev[("engine", "cmd_end")])
            self.assertEqual(ev[("01-write", "cmd_end")]["secs"], 2.0)
            self.assertEqual(ev[("01-write", "cmd_end")]["exit"], 1)


class Page(unittest.TestCase):
    def test_open_cmd_row_carries_data_t0_and_the_closed_pair_exit_and_secs(self):
        self.assertIn("n.dataset.t0=e.t", PAGE)
        self.assertIn("m.appendChild(tickEl(e.t))", PAGE)  # the span the page ticks every 250 ms
        self.assertIn("function tickEl(t0,t1){const s=el('span','tick');s.dataset.t0=t0", PAGE)
        self.assertRegex(PAGE, r"dataset\.exit=e\.exit")
        self.assertRegex(PAGE, r"dataset\.secs=")
        self.assertIn("'exit '+e.exit", PAGE)

    def test_append_only_no_rebuild_per_event(self):
        self.assertNotIn("innerHTML", PAGE)
        self.assertIn("pairKey(e){", PAGE)
        self.assertIn("e.src+'|'", PAGE)

    def test_autoscroll_pill(self):
        self.assertIn('<button id="follow"', PAGE)
        self.assertIn("function setFollow(on)", PAGE)
        self.assertIn("const stick=follow", PAGE)
        self.assertIn("if(!programmatic)setFollow(atBottom())", PAGE)  # scrolling up pauses, the tail resumes
        self.assertIn("$('follow').onclick=()=>{setFollow(true);toEnd()}", PAGE)
        self.assertIn("#follow.paused", CSS)

    def test_section_timers(self):
        self.assertIn("'d sectimer'", PAGE)
        self.assertIn("s.dataset.t0=e.t", PAGE)
        self.assertIn("s.tick.dataset.t1=e.t", PAGE)

    def test_phone_layout_rules(self):
        self.assertIn("width=device-width", PAGE)
        self.assertIn("overflow-x:hidden", CSS)
        self.assertIn("min-width:0", CSS)
        for sel in (".tail{", ".out{", ".row{", ".state{"):
            rule = CSS.split(sel, 1)[1].split("}", 1)[0]
            self.assertIn("overflow-wrap:anywhere", rule, sel)
        self.assertRegex(CSS, r"@media \(max-width:600px\)")
        for px in re.findall(r"(?<![\w.-])(?:min-)?width:\s*(\d+)px", CSS):
            self.assertLessEqual(int(px), 390)
        self.assertNotRegex(CSS, r"(?<!-)\bwidth:\s*(?:[4-9]\d\d|\d{4,})px")


if __name__ == "__main__":
    unittest.main()
