"""Weekly flake escalation keeps tests in the gate and deduplicates open fixes."""
import pytest
from tlkernel.flakes import FlakeRow

from tlland.domain.flake_escalate import Escalation, escalate, record


@pytest.mark.parametrize(
    ("times", "filed", "count"),
    [
        ((999_997.0, 999_998.0, 999_999.0), {}, None),
        ((999_997.0, 999_998.0, 999_999.0, 1_000_000.0), {}, 4),
        ((395_199.0, 999_998.0, 999_999.0, 1_000_000.0), {}, None),
        ((395_200.0, 999_998.0, 999_999.0, 1_000_000.0), {}, 4),
        ((999_996.0, 999_997.0, 999_998.0, 999_999.0, 1_000_000.0), {"test_a": "fix-1"}, None),
        ((999_996.0, 999_997.0, 999_998.0, 999_999.0, 1_000_000.0), {}, 5),
        ((999_997.0, 999_998.0, 999_999.0, 1_000_001.0), {}, None),
    ],
)
def test_weekly_escalation(
    times: tuple[float, ...], filed: dict[str, str], count: int | None,
) -> None:
    rows = [FlakeRow(test="test_a", t=t, how="retry") for t in reversed(times)]
    result = escalate(rows, filed, "test_a", now=1_000_000.0)
    if count is None:
        assert result is None
    else:
        assert result == Escalation(test="test_a", row_t=1_000_000.0, count=count)


def test_other_tests_are_not_counted() -> None:
    rows = [FlakeRow(test="test_a", t=999_999.0, how="retry") for _ in range(3)]
    rows.append(FlakeRow(test="test_b", t=1_000_000.0, how="retry"))
    assert escalate(rows, {}, "test_a", now=1_000_000.0) is None


def test_record_sets_bead_on_copy() -> None:
    row = FlakeRow(test="test_a", t=1_000_000.0, how="retry")
    recorded = record(row, "fix-1")
    assert recorded == row.replace(bead="fix-1")
    assert row.bead == ""


def test_escalation_has_no_skip_or_pass_output() -> None:
    rows = [FlakeRow(test="test_a", t=1_000_000.0, how="retry") for _ in range(4)]
    result = escalate(rows, {}, "test_a", now=1_000_000.0)
    assert isinstance(result, Escalation)
    assert not {"skip", "pass", "passed", "skipped"}.intersection(dir(result))
