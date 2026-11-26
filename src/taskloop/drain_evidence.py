"""Keep the attempt export before an upgrade can discard factory.db: one immutable JSON file per drain request, under the
artifacts root's `exports/`, which a database discard leaves alone.
Read-only on factory.db; the one writer of artifacts is `EvidenceFiles`."""

import json

from sqlite_store import SchemaError

from taskloop import attempt_export
from taskloop.attempt_export_store import ExportStore
from taskloop.evidence_files import EvidenceError, EvidenceFiles
from taskloop.factory_store import open_ro
from taskloop.machine_config import Loaded
from taskloop.rows_render import records


def save(loaded: Loaded, generation: int) -> str:
    """The saved file's path (one per drain request, named by its generation, so a retry writes the same file), or the reason
    none was saved (never raises: a completed drain stays completed)."""
    database, artifacts = loaded.settings.db.value, loaded.settings.artifacts.value
    try:
        reader = open_ro(database)
    except SchemaError as error:  # the drain's own check already passed, so only a race
        return f"not saved: {error}"
    if reader is None:
        return "not saved: factory.db could not be read"
    try:
        found = attempt_export.export(ExportStore(lambda: reader), None)
    finally:
        reader.close()
    if not isinstance(found, attempt_export.AttemptExport):
        return f"not saved: {found.detail or found.reason}"
    name = f"exports/attempts-drain{generation}.json"
    try:
        ref = EvidenceFiles(artifacts).put_export(name, json.dumps(records(found), sort_keys=True, indent=1))
    except EvidenceError as error:
        return f"not saved: {error}"
    return str((artifacts / ref.path).resolve())
