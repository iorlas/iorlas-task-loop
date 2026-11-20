"""Native observation's mapping of shelf identities; unknown and reused PIDs never prove idle."""

import pytest
from stream_proc import OwnedProcess, ProcessObservation

from taskloop.drain import observe
from taskloop.drain.models import Identity, Owner, Role, Seen


@pytest.mark.parametrize(
    ("observation", "group", "boot", "role", "expected"),
    [
        (ProcessObservation("matching", OwnedProcess(3, 3, "start", "boot")), False, "boot", Role.ENTRY, Seen.ALIVE),
        (ProcessObservation("gone"), False, "boot", Role.ENTRY, Seen.GONE),
        (ProcessObservation("gone"), True, "boot", Role.ENTRY, Seen.ALIVE),
        (ProcessObservation("gone"), True, "boot", Role.CALLER, Seen.UNKNOWN),
        (ProcessObservation("unknown"), False, "boot", Role.ENTRY, Seen.UNKNOWN),
        (ProcessObservation("different_process", OwnedProcess(3, 3, "reused", "boot")), False, "boot", Role.ENTRY, Seen.UNKNOWN),
        (ProcessObservation("gone"), True, "new-boot", Role.ENTRY, Seen.GONE),
    ],
)
def test_native_observation_is_conservative(
    monkeypatch: pytest.MonkeyPatch,
    observation: ProcessObservation,
    group: bool,
    boot: str,
    role: Role,
    expected: Seen,
) -> None:
    monkeypatch.setattr(observe, "observe_owned", lambda _process: observation)
    monkeypatch.setattr(observe, "group_alive", lambda _pgid: group)
    monkeypatch.setattr(observe, "identity", lambda: Identity(pid=4, pgid=4, start="self", boot=boot))
    owner = Owner(subject="attempt", role=role, identity=Identity(pid=3, pgid=3, start="start", boot="boot"))
    assert observe.observe(owner) is expected


def test_missing_boot_identity_never_proves_termination(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(observe, "observe_owned", lambda _process: ProcessObservation("gone"))
    monkeypatch.setattr(observe, "identity", lambda: None)
    owner = Owner(subject="attempt", role=Role.ENTRY, identity=Identity(pid=3, pgid=3, start="start", boot="boot"))
    assert observe.observe(owner) is Seen.UNKNOWN
