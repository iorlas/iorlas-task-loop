"""Immutable admitted inputs and observed execution evidence behind one file reader."""

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from any_agent import RunOutcome

from taskloop.attempt_types import AttemptKey, Evidence, FileRef
from taskloop.round_log import WORD
from taskloop.slot_state import shown

ENTRY_STATUS: Final = frozenset({"refused", "unavailable", "pending", "collected", "conflict", "failed"})
ENTRY_WORDS: Final = 8  # at most: status, reason, publish=, then=, verify=, claim=, release=, branch= (attempt_entry)


class EvidenceError(Exception):
    """Unavailable, changed or conflicting artifact bytes; never an empty fallback."""


class EvidenceFiles:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise EvidenceError("Artifact outside configured root")
        return path

    def read(self, ref: FileRef) -> str:
        try:
            data = self._path(ref.path).read_bytes()
            if hashlib.sha256(data).hexdigest() != ref.digest:
                raise EvidenceError("Artifact digest mismatch")
            return data.decode("utf-8")
        except (OSError, UnicodeError) as error:
            raise EvidenceError("Artifact unavailable") from error

    def _write(self, relative: str, text: str) -> FileRef:
        data = text.encode("utf-8")
        path = self._path(relative)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with path.open("xb") as stream:
                    stream.write(data)
            except FileExistsError:
                if path.read_bytes() != data:
                    raise EvidenceError("Conflicting immutable artifact") from None
        except OSError as error:
            raise EvidenceError("Cannot capture artifact") from error
        return FileRef(relative, hashlib.sha256(data).hexdigest())

    def directory(self, key: AttemptKey) -> str:
        encoded = json.dumps([key.attempt_id, key.dispatch_token, key.reservation_generation]).encode()
        return "attempts/" + hashlib.sha256(encoded).hexdigest()

    def entry_log(self, key: AttemptKey) -> Path:
        """The attempt's entry process log (`entry.log` in its key-derived directory), with that directory made."""
        path = self._path(self.directory(key) + "/entry.log")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def round_log(self) -> Path:
        """The scheduling rounds' append-only log (`rounds.log` beside `attempts/`), with the root made. Evidence for a
        person; nothing reads it for control."""
        path = self._path("rounds.log")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def log_round(self, line: str) -> None:
        """Append one line, opened as the launcher opens `entry.log` (0600, append, close-on-exec); OSError propagates."""
        descriptor = os.open(self.round_log(), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC, 0o600)
        with os.fdopen(descriptor, "ab") as stream:
            stream.write(line.encode("utf-8") + b"\n")

    def entry_tail(self, key: AttemptKey, cap: int = 4096) -> str | None:
        """Read-only: the last `cap` bytes of the attempt's entry log, None when it does not exist or cannot be read;
        creates nothing. Untrusted text: the caller keeps only lines of fixed words."""
        try:
            with self._path(self.directory(key) + "/entry.log").open("rb") as stream:
                size = stream.seek(0, 2)
                stream.seek(max(0, size - cap))
                return stream.read(cap).decode("utf-8", "replace")
        except (OSError, EvidenceError):
            return None

    def last_entry(self, key: AttemptKey) -> str | None:
        """The last line of the entry log made only of the entry's fixed words (its status word, then `reason`, `key=value`
        or `a:b` words of letters, digits and `_`), at most ENTRY_WORDS words; anything else in the log is never printed."""
        for line in reversed((self.entry_tail(key) or "").splitlines()[-20:]):
            words = line.split(" ")
            if words[0] in ENTRY_STATUS and len(words) <= ENTRY_WORDS and all(WORD.fullmatch(word) for word in words[1:]):
                return shown(line)
        return None

    def put_input(self, key: AttemptKey, text: str) -> FileRef:
        """The admitted input, written once under the attempt's key-derived directory before any external effect."""
        return self._write(self.directory(key) + "/input.txt", text)

    def prepare(self, key: AttemptKey, schema: Mapping[str, object]) -> tuple[str, str]:
        """Write the step kind's answer `schema` (`schema.json`) and return its path and the native answer path, without
        executing a harness."""
        directory = self.directory(key)
        ref = self._write(directory + "/schema.json", json.dumps(schema, sort_keys=True))
        return str(self._path(ref.path)), str(self._path(directory + "/native-answer.txt"))

    def capture(self, key: AttemptKey, raw: RunOutcome) -> Evidence:
        directory = self.directory(key)
        diagnostic = "\n".join([raw.summary.vendor, raw.summary.tail, raw.watch.msg, raw.watch.words, raw.secret or "", *raw.stream_tail])
        return Evidence(self._write(directory + "/stdout.txt", raw.out), self._write(directory + "/stderr.txt", raw.err),
                        self._write(directory + "/answer.txt", raw.summary.text), self._write(directory + "/diagnostics.txt", diagnostic))
