"""Bounded duration snapshots and an immutable final seal, independent of execution state."""

import os
import tempfile
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from taskloop.duration_evidence import DurationSample, DurationState

CAP: Final = 4096
ACTIVE: Final = "duration.json"
SEALED: Final = "duration-sealed.json"


def _load(path: Path, identity: str) -> DurationSample:
    with path.open("rb") as stream:
        data = stream.read(CAP + 1)
    if len(data) > CAP:
        raise ValueError("Duration evidence exceeds cap")
    sample = DurationSample.model_validate_json(data)
    if sample.execution != identity:
        raise ValueError("Duration execution identity mismatch")
    expected = DurationState.SEALED if path.name == SEALED else DurationState.ACTIVE
    if sample.state is not expected:
        raise ValueError("Duration state mismatch")
    return sample


def read(directory: Path, identity: str) -> DurationSample | None:
    try:
        try:
            return _load(directory / SEALED, identity)
        except FileNotFoundError:
            return _load(directory / ACTIVE, identity)
    except (OSError, ValueError, ValidationError):
        return None


def _publish(directory: Path, name: str, data: bytes, *, immutable: bool = False) -> None:
    if len(data) > CAP:
        raise ValueError("Duration evidence exceeds cap")
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=directory, prefix=".duration-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            if immutable:
                os.link(temporary, directory / name)
            else:
                os.replace(temporary, directory / name)
        finally:
            temporary.unlink(missing_ok=True)
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write(directory: Path, identity: str, sample: DurationSample) -> None:
    # Validate even an in-process caller that bypassed pydantic with model_copy/model_construct.
    sample = DurationSample.model_validate(sample.model_dump())
    if sample.execution != identity:
        raise ValueError("Duration execution identity mismatch")
    try:
        sealed = _load(directory / SEALED, identity)
    except FileNotFoundError:
        sealed = None
    if sealed is not None:
        if sample != sealed:
            raise ValueError("Conflicting sealed duration evidence")
        return
    try:
        previous = _load(directory / ACTIVE, identity)
    except FileNotFoundError:
        previous = None
    if previous is not None:
        if sample.number <= previous.number or sample.elapsed < previous.elapsed:
            raise ValueError("Decreasing duration sample")
        if previous.command_offset is not None and (sample.command_offset is None or sample.command_offset < previous.command_offset):
            raise ValueError("Decreasing command offset")
    name = SEALED if sample.state is DurationState.SEALED else ACTIVE
    data = sample.model_dump_json().encode()
    try:
        _publish(directory, name, data, immutable=sample.state is DurationState.SEALED)
    except FileExistsError:
        if _load(directory / SEALED, identity) != sample:
            raise ValueError("Conflicting sealed duration evidence") from None


def invalidate(directory: Path) -> None:
    if not (directory / SEALED).exists():
        _publish(directory, ACTIVE, b"null")
