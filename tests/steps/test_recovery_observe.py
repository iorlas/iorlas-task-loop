"""Stop proof includes the native process identity, boot and worker group."""

import pytest
from stream_proc import OwnedProcess, ProcessObservation

from taskloop import owned_processes
from taskloop.attempt_types import Seen as NativeSeen
from taskloop.drain.models import Identity, Seen
from taskloop.recovery.observe import NativeProcesses


@pytest.mark.parametrize(
    ("seen", "group", "boot", "expected"),
    [
        ("matching", False, "boot", Seen.ALIVE),
        ("unknown", False, "boot", Seen.UNKNOWN),
        ("gone", False, "boot", Seen.GONE),
        ("gone", True, "boot", Seen.ALIVE),
        ("different_process", True, "boot", Seen.ALIVE),
        ("different_process", False, "boot", Seen.GONE),
        ("gone", True, "new-boot", Seen.GONE),
        ("gone", True, None, Seen.UNKNOWN),
    ],
)
def test_process_observation_never_confuses_pid_reuse_with_an_empty_group(
    monkeypatch: pytest.MonkeyPatch, seen: NativeSeen, group: bool, boot: str | None, expected: Seen,
) -> None:
    observation = ProcessObservation(seen, OwnedProcess(8, 8, "worker", "boot"))
    monkeypatch.setattr(owned_processes, "observe_owned", lambda _process: observation)
    monkeypatch.setattr(owned_processes, "group_alive", lambda _pgid: group)
    monkeypatch.setattr(owned_processes, "current_boot", lambda: boot)
    result = NativeProcesses().process(Identity(pid=8, pgid=8, start="worker", boot="boot"))
    assert result.seen is expected and result.explanation


@pytest.mark.parametrize(
    ("seen", "expected"),
    [("matching", Seen.ALIVE), ("unknown", Seen.UNKNOWN), ("gone", Seen.GONE), ("different_process", Seen.GONE)],
)
def test_entry_observations_use_the_registered_identity(monkeypatch: pytest.MonkeyPatch, seen: NativeSeen, expected: Seen) -> None:
    identities: list[OwnedProcess] = []

    def observe(process: OwnedProcess) -> ProcessObservation:
        identities.append(process)
        return ProcessObservation(seen)

    monkeypatch.setattr(owned_processes, "observe_owned", observe)
    result = NativeProcesses().entry((7, "entry", "boot"))
    assert result.seen is expected and result.explanation
    assert len(identities) == 1 and identities[0].pid == 7 and identities[0].start == "entry"
