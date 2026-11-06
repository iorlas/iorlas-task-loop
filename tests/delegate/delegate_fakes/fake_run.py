"""Replace the supervisor's process run: the CLI's stdout lines go through the real parse, routing and summary, no process is spawned."""

import json
from collections.abc import Mapping, Sequence
from types import TracebackType
from unittest import mock

from any_agent.protocol import LaunchSpec
from any_agent.supervisor import RunOutcome, Supervisor


class Replay:
    """A patch of Supervisor.run, used as a context manager; the specs it was given are kept in `.specs`."""

    def __init__(self, lines: Sequence[Mapping[str, object] | str], rc: int, err: str, timed_out: bool) -> None:
        self.specs: list[LaunchSpec] = []
        text = [json.dumps(x) if isinstance(x, Mapping) else x for x in lines]

        def run(supervisor: Supervisor, spec: LaunchSpec, timeout: float) -> RunOutcome:
            self.specs.append(spec)
            killed = False
            for line in text:
                if supervisor._on_out(line + "\n"):
                    killed = True
                    break
            supervisor.out.timed_out = timed_out
            return supervisor.finish(rc, "".join(x + "\n" for x in text), err, killed)

        self.patcher = mock.patch.object(Supervisor, "run", run)

    def __enter__(self) -> Replay:
        self.patcher.start()
        return self

    def __exit__(self, kind: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None) -> None:
        self.patcher.stop()


def replay(lines: Sequence[Mapping[str, object] | str], rc: int = 0, err: str = "", timed_out: bool = False) -> Replay:
    """-> a patcher: Supervisor.run feeds `lines` (dicts or strings) as the worker's stdout and ends with `rc`;
    the specs it got are kept in `.specs`."""
    return Replay(lines, rc, err, timed_out)
