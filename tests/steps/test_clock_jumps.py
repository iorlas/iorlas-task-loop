"""Clock evidence preserves separate discontinuities and stays bounded independently of agent activity."""

from pathlib import Path

import pytest

from taskloop.attempt_types import AttemptKey
from taskloop.clock_jumps import ClockContext, ClockDirection, ClockJump, ClockJumps, encode
from taskloop.evidence_files import TRUNCATED, EvidenceFiles

KEY = AttemptKey("attempt", "dispatch", 1)


@pytest.mark.parametrize("context", list(ClockContext))
@pytest.mark.parametrize("broken", [False, True])
def test_distinct_opposing_jumps_ignore_elapsed_time_noise_and_stable_offsets(context: ClockContext, broken: bool) -> None:
    now = [1000.0, 10.0]
    records: list[ClockJump] = []

    def write(jump: ClockJump) -> None:
        records.append(jump)
        if broken:
            raise OSError("full")

    observer = ClockJumps(context, lambda: now[0], lambda: now[1], write)
    for wall, monotonic in [(1002, 12), (1005, 14), (8207, 16), (8209, 18), (-6189, 20), (-6187, 22)]:
        now[:] = [wall, monotonic]
        observer.sample()
    assert [record.context for record in records] == [context, context]
    assert [record.direction for record in records] == [ClockDirection.FORWARD, ClockDirection.BACKWARD]
    assert [record.difference for record in records] == [7200, -14400]
    assert [(record.wall_before, record.wall_after, record.monotonic_elapsed) for record in records] == [
        (1005, 8207, 2), (8209, -6189, 2),
    ]
    assert ClockJump.model_validate_json(encode(records[0])) == records[0]
    assert '"context":"' + context.value + '"' in encode(records[0])


def test_clock_evidence_is_separate_private_and_capped_across_appends(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    files = EvidenceFiles(tmp_path)
    path = files.clock_jumps_path(KEY)
    assert not path.exists() and not path.parent.exists()
    jump = ClockJump(
        context=ClockContext.ACTIVE, direction=ClockDirection.FORWARD,
        wall_before=1000, wall_after=8202, monotonic_elapsed=2, difference=7200,
    )
    line = (encode(jump) + "\n").encode()
    monkeypatch.setattr("taskloop.evidence_files.CLOCK_JUMPS_CAP", len(line) + 3)
    files.append_clock_jump(KEY, jump)
    EvidenceFiles(tmp_path).append_clock_jump(KEY, jump)
    files.append_clock_jump(KEY, jump)
    assert path.read_bytes() == line + line[:3] + TRUNCATED
    assert path.stat().st_mode & 0o777 == 0o600
    assert not files.events_path(KEY).exists()
