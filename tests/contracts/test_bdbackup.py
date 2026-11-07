"""The bead tracker's backup: a daily JSONL export (seven kept) and a monthly restore drill that reads the newest back. bd is a fake."""
import json
from datetime import UTC, datetime
from pathlib import Path

from tlkernel import bdbackup
from tlkernel.paths import ConfigDir

DAY = 86400.0
T0 = datetime(2026, 11, 1, 12, tzinfo=UTC).timestamp()


class FakeBd:
    def __init__(self, issues=3, live=None, code=0):
        self.issues, self.live, self.code, self.calls = issues, issues if live is None else live, code, []

    def __call__(self, argv):
        self.calls.append(argv[0])
        if argv[0] == "count":
            return 0, f"{self.live}\n", ""
        if self.code:
            return self.code, "", "dolt is down"
        lines = [json.dumps({"_type": "issue", "id": f"t-{n}"}) for n in range(self.issues)] + [json.dumps({"_type": "memory", "k": "m"})]
        Path(argv[2]).write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 0, f"Exported {self.issues} issues and 1 memories to {argv[2]}\n", ""


def cfg_of(workdir):
    return ConfigDir(workdir)


def test_nine_days_keep_seven_and_a_second_call_in_a_day_runs_bd_once(workdir):
    cfg, bd = cfg_of(workdir), FakeBd()
    for day in range(9):
        assert bdbackup.export(cfg, "r", bd, T0 + day * DAY) == ""
        assert bdbackup.export(cfg, "r", bd, T0 + day * DAY + 60) == ""
    assert bd.calls == ["export"] * 9
    kept = bdbackup.exports(cfg, "r")
    assert [p.name for p in kept] == [f"bd-r-202611{d:02d}.jsonl" for d in range(9, 2, -1)]
    assert sorted(p.name for p in kept[0].parent.glob("*.count")) == sorted(p.with_suffix(".count").name for p in kept)


def test_a_failing_bd_leaves_no_file_and_says_why(workdir):
    cfg = cfg_of(workdir)
    why = bdbackup.export(cfg, "r", FakeBd(code=1), T0)
    assert "dolt is down" in why
    assert bdbackup.exports(cfg, "r") == []
    assert not list((cfg.root / "backups").glob("*.tmp"))


def test_the_drill_passes_on_a_good_export_and_runs_once_a_month(workdir):
    cfg, bd = cfg_of(workdir), FakeBd(issues=3, live=5)
    bdbackup.export(cfg, "r", bd, T0)
    assert bdbackup.drill(cfg, "r", bd, T0) == ""
    assert bdbackup.last_drill(cfg, "r") == {"month": "202611", "file": "bd-r-20261101.jsonl", "ok": True, "why": ""}
    before = len(bd.calls)
    bdbackup.drill(cfg, "r", bd, T0 + DAY)
    assert len(bd.calls) == before  # same month: not again
    bdbackup.drill(cfg, "r", bd, T0 + 31 * DAY)
    assert len(bd.calls) == before + 1  # next month: again


def test_the_drill_without_an_export_is_not_a_failure(workdir):
    assert bdbackup.drill(cfg_of(workdir), "r", FakeBd(), T0) == ""
    assert bdbackup.last_drill(cfg_of(workdir), "r") == {}


def test_a_truncated_file_a_count_mismatch_and_a_lower_live_count_each_fail_with_their_reason(workdir):
    cfg = cfg_of(workdir)
    bdbackup.export(cfg, "r", FakeBd(issues=3), T0)
    path = bdbackup.exports(cfg, "r")[0]
    assert bdbackup.check(path, FakeBd()) == ""
    assert "fewer than the 3" in bdbackup.check(path, FakeBd(issues=3, live=2))
    path.with_suffix(".count").write_text("4")
    assert "holds 3 issues, bd reported 4" in bdbackup.check(path, FakeBd())
    path.write_text('{"_type": "issue", "id": "t-0"}\n{"_type": "iss', encoding="utf-8")
    assert "does not read back" in bdbackup.check(path, FakeBd())


def test_nightly_says_nothing_when_all_is_well_and_the_reason_when_not(workdir):
    cfg = cfg_of(workdir)
    assert bdbackup.nightly(cfg, "r", FakeBd(), T0) == []
    assert bdbackup.nightly(cfg_of(workdir / "other"), "r", FakeBd(code=2), T0)[0].startswith("loop: bd backup: bd export exited 2")
