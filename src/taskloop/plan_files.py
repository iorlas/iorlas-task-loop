"""Immutable admitted inputs and observed execution evidence behind one file reader."""

import hashlib
import json
from pathlib import Path
from typing import Final

from any_agent import RunOutcome

from taskloop.plan_types import DISPOSITIONS, AttemptKey, Evidence, FileRef

# The structural answer contract Codex forwards as an OpenAI strict response format: a plain object at the top level (no
# allOf/anyOf/oneOf/not/enum/if there), every property required, nullable by type list, no composition keywords at all.
# The cross-field rule (planned needs the expected path and a commit) and value bounds belong to decode_plan_answer alone.
ANSWER_SCHEMA: Final = {
    "type": "object",
    "additionalProperties": False,
    "required": ["disposition", "plan_path", "commit", "explanation"],
    "properties": {
        "disposition": {"type": "string", "enum": list(DISPOSITIONS)},
        "plan_path": {"type": ["string", "null"]},
        "commit": {"type": ["string", "null"], "pattern": "^([0-9a-f]{40}|[0-9a-f]{64})$"},
        "explanation": {"type": "string"},
    },
}


class EvidenceError(Exception):
    """Unavailable, changed or conflicting artifact bytes; never an empty fallback."""


class PlanFiles:
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

    def put_input(self, key: AttemptKey, text: str) -> FileRef:
        """The admitted input, written once under the attempt's key-derived directory before any external effect."""
        return self._write(self.directory(key) + "/input.txt", text)

    def prepare(self, key: AttemptKey) -> tuple[str, str]:
        """Return owned schema and native answer paths, without executing a harness."""
        directory = self.directory(key)
        ref = self._write(directory + "/schema.json", json.dumps(ANSWER_SCHEMA, sort_keys=True))
        return str(self._path(ref.path)), str(self._path(directory + "/native-answer.txt"))

    def capture(self, key: AttemptKey, raw: RunOutcome) -> Evidence:
        directory = self.directory(key)
        diagnostic = "\n".join([raw.summary.vendor, raw.summary.tail, raw.watch.msg, raw.watch.words, raw.secret or "", *raw.stream_tail])
        return Evidence(self._write(directory + "/stdout.txt", raw.out), self._write(directory + "/stderr.txt", raw.err),
                        self._write(directory + "/answer.txt", raw.summary.text), self._write(directory + "/diagnostics.txt", diagnostic))
