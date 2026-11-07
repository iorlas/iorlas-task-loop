"""Report text and digest window/state decisions, with memory-only inputs."""

import io
import json
from functools import partial

import pytest

from taskloop.app.report import card as report
from taskloop.app.report import planner, reflect
from tlkernel.identity import Identity


@pytest.fixture
def output(monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr(report, "print", partial(print, file=stream), raising=False)
    monkeypatch.setattr(planner, "print", partial(print, file=stream), raising=False)
    monkeypatch.setattr(reflect, "print", partial(print, file=stream), raising=False)
    return stream


def test_planner_table_order_and_spacing(output):
    p = {"calls": 3, "beads": 2, "first": 2, "again": 1, "amend": 0, "back": 0, "other": 0, "input": 3000000, "median_input": 1000000}
    p = dict(p, per_bead=[dict(p, bead="small", calls=1, input=1000000), dict(p, bead="large", calls=2, input=2000000)])
    planner.print_planner(p)
    assert output.getvalue() == (
        "planner: 3 calls on 2 beads: 2 first plans, 1 full plans again, 0 amends, 0 check send-backs, 0 other; "
        "input 3.0M, median 1000k per call\n"
        "  bead                       calls first again amend  back other   input M\n"
        "  large                          2     2     1     0     0     0      2.00\n"
        "  small                          1     2     1     0     0     0      1.00\n"
    )


@pytest.mark.parametrize("as_json", [False, True])
@pytest.mark.parametrize("classes", [[], ["landed", "reclaimed", "superseded", "pending", "unknown"], ["lost"]])
def test_lost_rows_summary_and_status(classes, as_json, monkeypatch, output):
    monkeypatch.setattr(report, "stamp", lambda _: "2026-10-21 06:00")
    rows = [dict(branch="task/x", sha="1234567890", time=0, why="é", **{"class": cls}) for cls in classes]
    assert report.print_lost(rows, as_json=as_json) == int("lost" in classes)
    if as_json:
        expected = json.dumps(rows, indent=1, ensure_ascii=False) + "\n"
    else:
        expected = "".join(f"{cls:<9} {'task/x':<28} 12345678 2026-10-21 06:00  é\n" for cls in classes if cls != "landed")
        expected += (
            f"{classes.count('lost')} lost, {classes.count('pending')} pending, {classes.count('unknown')} unknown, "
            f"{classes.count('reclaimed')} reclaimed, {classes.count('superseded')} superseded, {classes.count('landed')} landed"
            " (commits on task/* and wip/* not on the base)\n"
        )
    assert output.getvalue() == expected


@pytest.mark.parametrize(
    ("last", "since", "until", "dry", "busy", "expected_since", "write"),
    [
        (0, None, None, False, False, 9, True),
        (2, None, None, False, False, 7, True),
        (9, None, None, True, False, 9, False),
        (9, None, None, False, True, 9, False),
        (9, "2h", "1h", False, False, 10 - 7200 / 86400, False),
    ],
)
def test_digest_window_state_and_json(last, since, until, dry, busy, expected_since, write, monkeypatch, output):
    now = 10 * reflect.DAY
    state = {"until": last * reflect.DAY, "other": "kept"}
    writes = []
    calls = []
    who = Identity(actor="test", home="config")
    d = {"items": 0, "clusters": [], "actions": [], "busy": busy}
    monkeypatch.setattr(reflect.time, "time", lambda: now)
    monkeypatch.setattr(reflect, "read_state", lambda _: dict(state))
    monkeypatch.setattr(reflect, "write_state", lambda _, s: writes.append(s))
    monkeypatch.setattr(reflect, "digest", lambda *args, **kw: calls.append((args, kw)) or d)
    assert reflect.report_digest(who, since, until, dry_run=dry, as_json=True) == 0
    assert calls == [((who, expected_since * reflect.DAY, now - 3600 if until else now), {"dry": dry})]
    assert writes == ([dict(state, until=now)] if write else [])
    assert output.getvalue() == json.dumps(d, indent=1, default=str) + "\n"


@pytest.mark.parametrize("dry", [False, True])
def test_digest_text(dry, monkeypatch, output):
    action = {"action": "new", "cause": "crash", "title": "x" * 70, "repo": "project", "bead": "", "runs": [1, 2]}
    monkeypatch.setattr(reflect, "read_state", lambda _: {})
    monkeypatch.setattr(reflect, "digest", lambda *_, **kw: {"items": 3, "clusters": [1, 2], "actions": [action]})
    assert reflect.report_digest(Identity(actor="test", home="config"), "1h", None, dry_run=dry, as_json=False) == 0
    assert output.getvalue() == (
        f"3 bad items in 2 causes, 1 recurring{' (dry run)' if dry else ''}\n  new       [crash] {'x' * 60} -> project - (2 runs)\n"
    )


@pytest.mark.parametrize("detail", [False, True])
def test_card_text_branches(detail, monkeypatch, output):
    monkeypatch.setattr(report, "stamp", lambda _: "2026-10-21 06:00")
    c: dict[str, object] = {
        "repo": "project",
        "since": 0,
        "until": 1,
        "runs": 2,
        "beads": 2,
        "landed": 1,
        "landed_no_ask": 1,
        "parked": 0,
        "paused": 0,
        "failed": 1,
        "asks": {"count": 2, "beads": 1, "owner": 1, "supervisor": 0, "open": 0, "unknown": int(detail)},
        "crashes": 1,
        "lost": 1,
        "pending_list": [],
        "land": {"tries": 0},
        "minutes": {"median": 2, "p90": 3},
        "rounds": 4,
        "replans": 5,
        "tokens": {"lane": {"worker": {"in": 1500000, "cached": 500000, "out": 1234}}, "role": {}},
        "crash_list": [{"t": 0, "bead": "x-1", "why": "oops"}],
        "lost_list": [{"branch": "task/x-1", "sha": "123456789", "subject": "é", "why": "closed"}],
        "per_bead": [
            {"state": "landed", "asks": 0},
            {"state": "failed", "bead": "x-1", "asks": 2, "answers": ["owner", "open"], "why": "oops"},
        ],
        "m2": {"pass": not detail, "checks": {"asks": {"ok": not detail, "value": 2, "want": 0}}},
    }
    if detail:
        c.update(
            land={"tries": 2, "retried": 1, "median_s": {"gate": 3.2}, "causes": {"red": 1}},
            kinds={"success": 2, "failure": 1},
            main={"red": True, "gate_red": True, "reverts": [{"sha": "123456789", "subject": "undo"}]},
        )
    report.print_card(c)
    assert output.getvalue() == (
        "tl report project  2026-10-21 06:00 -> 2026-10-21 06:00  (runs overlapping the window: 2)\n"
        "  beads 2   landed 1   landed with no ask 1   parked 0   paused 0   failed 1\n"
        f"  asks 2 on 1 beads: owner 1, supervisor 0, open 0{', unknown 1' if detail else ''}\n"
        "  crashes 1   lost 1   pending branches 0\n"
        + ("  land    2 tries, 1 retried (red 1)  median gate 3s\n" if detail else "")
        + "  minutes per bead: median 2, p90 3   fix rounds 4   replans 5\n"
        "  tokens lane  worker    1.5M in (0.5M cached), 1k out\n"
        "  crash   06:00 x-1  oops\n"
        "  lost    task/x-1 12345678 é  closed\n"
        "  failed  x-1  asks: owner,open  oops\n"
        + ("  outcomes success 2, failure 1\n" if detail else "")
        + ("  main    RED: reverted 12345678 undo; the last release gate failed\n" if detail else "  main    green\n")
        + ("M2 FAIL: asks 2 (want 0)\n" if detail else "M2 PASS\n")
    )
