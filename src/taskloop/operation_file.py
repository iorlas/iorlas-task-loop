"""Atomic, bounded operation evidence, separate from factory control state."""

import os
import tempfile
from pathlib import Path
from typing import Final

from taskloop.operation_evidence import OperationSample, OperationState

CAP: Final = 4096
ACTIVE: Final = "active.json"
FINAL: Final = "final.json"
OPERATIONS: Final = "operations"


def _load(path: Path, identity: str) -> OperationSample:
    with path.open("rb") as stream:
        data = stream.read(CAP + 1)
    if len(data) > CAP:
        raise ValueError("Operation evidence exceeds cap")
    sample = OperationSample.model_validate_json(data)
    if sample.attempt != identity or sample.operation != path.parent.name:
        raise ValueError("Operation identity mismatch")
    if (sample.state is OperationState.ACTIVE) != (path.name == ACTIVE):
        raise ValueError("Operation state mismatch")
    return sample


def read(directory: Path, identity: str) -> tuple[OperationSample, ...]:
    samples: list[OperationSample] = []
    try:
        for path in (directory / OPERATIONS).iterdir():
            if path.is_symlink() or not path.is_dir():
                continue
            try:
                try:
                    sample = _load(path / FINAL, identity)
                except FileNotFoundError:
                    sample = _load(path / ACTIVE, identity)
                samples.append(sample)
            except OSError, ValueError:
                continue
    except OSError:
        pass
    return tuple(sorted(samples, key=lambda sample: (sample.started_at, sample.operation)))


def _publish(directory: Path, name: str, data: bytes) -> None:
    if len(data) > CAP:
        raise ValueError("Operation evidence exceeds cap")
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=directory, prefix=".operation-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.link(temporary, directory / name)
        finally:
            temporary.unlink(missing_ok=True)
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write(directory: Path, identity: str, sample: OperationSample) -> None:
    sample = OperationSample.model_validate(sample.model_dump(warnings=False))
    if sample.attempt != identity:
        raise ValueError("Operation attempt identity mismatch")
    path = directory / OPERATIONS / sample.operation
    try:
        final = _load(path / FINAL, identity)
    except FileNotFoundError:
        final = None
    if final is not None:
        if final != sample:
            raise ValueError("Conflicting final operation evidence")
        return
    if sample.state is not OperationState.ACTIVE:
        active = _load(path / ACTIVE, identity)
        expected = sample.model_copy(update={"elapsed": 0.0, "state": OperationState.ACTIVE})
        if active != expected:
            raise ValueError("Operation start mismatch")
    name = ACTIVE if sample.state is OperationState.ACTIVE else FINAL
    try:
        _publish(path, name, sample.model_dump_json().encode())
    except FileExistsError:
        if _load(path / name, identity) != sample:
            raise ValueError("Conflicting operation evidence") from None
