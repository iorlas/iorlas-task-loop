"""Land history uses recorded facts without taking any delivery action."""

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from doubles import CHECKS
from land_bench import LandBench, bench

from taskloop.check_store import ChecksRow, CheckStore
from taskloop.dash_land import build_events
from taskloop.dash_model import LandEventKind, iso
from taskloop.land_store import LandRow, LandStore


@pytest.fixture
def world(tmp_path: Path) -> Iterator[LandBench]:
    found = bench(tmp_path)
    yield found
    found.con.close()


def checked(world: LandBench) -> ChecksRow:
    row = CheckStore(lambda: world.con).row(CHECKS)
    assert row is not None
    return row


class Candidates(LandStore):
    """Semantic candidate reader, including incomplete observations after a crash."""

    def __init__(self, rows: tuple[LandRow, ...]) -> None:
        self.rows = rows

    def of_checks(self, checks: str) -> tuple[LandRow, ...]:
        return tuple(row for row in self.rows if row.checks == checks)


def test_readiness_needs_passed_released_checks_and_never_creates_a_candidate(world: LandBench) -> None:
    row = checked(world)
    events = build_events(world.lands, ((row, 1, False),), lambda _entry: "matching")
    ready, = events
    assert ready.kind is LandEventKind.READY and ready.candidate_id is None
    assert ready.at == iso(max(row.concluded_at or 0, row.released_at or 0))
    assert ready.waits[0].open and ready.waits[0].ended_at is None
    for unready in (replace(row, conclusion="failed"), replace(row, released_at=None)):
        assert build_events(world.lands, ((unready, 1, False),), lambda _entry: "matching") == ()
    assert world.rows() == () and world.tracker == [] and world.repo.pushes == 0 and world.reservations() == []


def test_every_candidate_stays_in_checks_chain_order_with_unknown_try_times(world: LandBench) -> None:
    world.land()
    original, = world.rows()
    old = replace(checked(world), abandoned=True)
    current = replace(old, key=replace(old.key, attempt_id="next-checks"), abandoned=False)
    first = replace(original, validation="failed", reason="validation failed", delivery=None, delivered_at=None,
                    close=None, closed_at=None, superseded="moved", superseded_at=20)
    second = replace(original, key=replace(original.key, attempt_id="second"), number=2)
    third = replace(first, key=replace(original.key, attempt_id="third"), checks=current.key.attempt_id)
    events = build_events(Candidates((first, second, third)), ((old, 1, False), (current, 2, False)), lambda _entry: "matching")
    assert [(event.kind, event.checks_n, event.candidate_n) for event in events] == [
        (LandEventKind.READY, 1, None), (LandEventKind.TRIED, 1, 1), (LandEventKind.TRIED, 1, 2),
        (LandEventKind.LANDED, 1, 2), (LandEventKind.READY, 2, None), (LandEventKind.TRIED, 2, 1)]
    assert all(event.past for event in events[:4]) and not any(event.past for event in events[4:])
    assert len({event.id for event in events}) == len(events)
    assert all(event.at is None for event in events if event.kind is LandEventKind.TRIED)
    assert all(not wait.open for event in events[:4] for wait in event.waits)
    assert events[0].waits[0].ended_at is None and not events[0].waits[0].open


@pytest.mark.parametrize("closed,released", [(False, True), (True, False), (True, True)])
def test_landed_requires_delivery_completion_and_release(world: LandBench, closed: bool, released: bool) -> None:
    world.land()
    row, = world.rows()
    row = replace(row, slot="s1", validated_at=11, delivered_at=15, close=row.close if closed else None,
                  closed_at=20 if closed else None, released_at=25 if released else None)
    events = build_events(Candidates((row,)), ((checked(world), 1, False),), lambda _entry: "matching")
    assert (events[-1].kind is LandEventKind.LANDED) == (closed and released)
    if closed and released:
        assert events[-1].at == iso(25)
    else:
        assert any(wait.open for wait in events[-1].waits)
    no_delivery = replace(row, delivery=None, delivered_at=None)
    unfinished = build_events(Candidates((no_delivery,)), ((checked(world), 1, False),), lambda _entry: "matching")
    assert unfinished[-1].kind is LandEventKind.TRIED


def test_completed_waits_and_missing_completion_times_are_retained(world: LandBench) -> None:
    world.land()
    row, = world.rows()
    row = replace(row, slot="s1", validated_at=10, released_at=12, delivered_at=15, closed_at=20)
    events = build_events(Candidates((row,)), ((checked(world), 1, False),), lambda _entry: "matching")
    tried = events[1]
    assert [(wait.started_at, wait.ended_at, wait.open) for wait in tried.waits] == [
        (iso(10), iso(12), False), (iso(12), iso(15), False), (iso(15), iso(20), False)]
    missing = replace(row, closed_at=None)
    assert build_events(Candidates((missing,)), ((checked(world), 1, False),), lambda _entry: "matching")[-1].at is None
    invalid = replace(row, delivered_at=5)
    waits = build_events(Candidates((invalid,)), ((checked(world), 1, False),), lambda _entry: "matching")[1].waits
    assert waits[1].started_at is waits[1].ended_at is None
    superseded = replace(row, delivery=None, delivered_at=None, close=None, closed_at=None, superseded="moved", superseded_at=18)
    events = build_events(Candidates((superseded,)), ((checked(world), 1, False),), lambda _entry: "matching")
    release, integration, retry = events[1].waits
    assert (release.started_at, release.ended_at) == (iso(10), iso(12))
    assert (integration.started_at, integration.ended_at, integration.open) == (iso(12), iso(18), False)
    assert retry.started_at == iso(18) and retry.open


def test_active_validation_has_no_wait_and_unknown_process_has_no_invented_start(world: LandBench) -> None:
    world.land()
    row, = world.rows()
    row = replace(row, slot="s1", validation=None, validated_at=None, released_at=None,
                  delivery=None, delivered_at=None, close=None, closed_at=None, entry=(99, "start", "boot"), deadline=999)
    chain = ((checked(world), 1, False),)
    active = build_events(Candidates((row,)), chain, lambda _entry: "matching")
    assert active[-1].waits == ()
    unknown = build_events(Candidates((row,)), chain, lambda _entry: "unknown")
    wait, = unknown[-1].waits
    assert wait.open and wait.started_at is None and "unconfirmed" in wait.awaited
    assert unknown[-1].model_dump(mode="json")["kind"] == "tried"


def test_failed_validation_waits_for_release_before_another_try(world: LandBench) -> None:
    world.land()
    row, = world.rows()
    row = replace(row, slot="s1", validation="failed", validated_at=10, released_at=None,
                  delivery=None, delivered_at=None, close=None, closed_at=None)
    chain = ((checked(world), 1, False),)
    events = build_events(Candidates((row,)), chain, lambda _entry: "matching")
    wait, = events[-1].waits
    assert wait.open and wait.started_at == iso(10) and "slot" in wait.awaited
    released = replace(row, released_at=20)
    events = build_events(Candidates((released,)), chain, lambda _entry: "matching")
    release, retry = events[-1].waits
    assert not release.open and release.ended_at == iso(20)
    assert retry.open and retry.started_at == iso(20)
    newer = replace(checked(world), key=replace(CHECKS, attempt_id="new-checks"), conclusion="failed")
    events = build_events(Candidates((released,)), (*chain, (newer, 2, False)), lambda _entry: "matching")
    assert all(not wait.open for event in events for wait in event.waits)
