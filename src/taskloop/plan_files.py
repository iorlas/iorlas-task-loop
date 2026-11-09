"""Immutable admitted inputs and observed execution evidence behind one file reader."""

import hashlib
import json
from pathlib import Path

from any_agent import RunOutcome

from taskloop.plan_types import AttemptKey, Evidence, FileRef


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

    def put_input(self, key: AttemptKey, text: str) -> FileRef:
        """The admitted input, written once under the attempt's key-derived directory before any external effect."""
        return self._write(self.directory(key) + "/input.txt", text)

    def prepare(self, key: AttemptKey, expected_path: str) -> tuple[str, str]:
        """Return owned schema and native answer paths, without executing a harness."""
        path = {"anyOf": [{"type": "null"}, {"type": "string", "const": expected_path}]}
        commit = {"anyOf": [{"type": "null"}, {"type": "string", "pattern": "^([0-9a-f]{40}|[0-9a-f]{64})$"}]}
        schema = {
            "type": "object", "additionalProperties": False,
            "required": ["disposition", "plan_path", "commit", "explanation"],
            "properties": {"disposition": {"enum": ["planned", "incomplete", "needs_owner"]}, "plan_path": path,
                           "commit": commit, "explanation": {"type": "string", "maxLength": 2000}},
            "allOf": [{"if": {"properties": {"disposition": {"const": "planned"}}},
                       "then": {"properties": {"plan_path": {"const": expected_path}, "commit": {"type": "string"}}}}],
        }
        directory = self.directory(key)
        ref = self._write(directory + "/schema.json", json.dumps(schema, sort_keys=True))
        return str(self._path(ref.path)), str(self._path(directory + "/native-answer.txt"))

    def capture(self, key: AttemptKey, raw: RunOutcome) -> Evidence:
        directory = self.directory(key)
        diagnostic = "\n".join([raw.summary.vendor, raw.summary.tail, raw.watch.msg, raw.watch.words, raw.secret or "", *raw.stream_tail])
        return Evidence(self._write(directory + "/stdout.txt", raw.out), self._write(directory + "/stderr.txt", raw.err),
                        self._write(directory + "/answer.txt", raw.summary.text), self._write(directory + "/diagnostics.txt", diagnostic))
