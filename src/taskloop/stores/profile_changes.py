"""The profile-change audit, through the shared atomic JSONL appender."""
from taskloop.contracts import wire
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.profile_changes import ProfileChange
from taskloop.contracts.stores import JsonlStore


def decode(data: object) -> ProfileChange:
    return wire.load(ProfileChange, data)


def profile_changes(cfg: ConfigDir) -> JsonlStore[ProfileChange]:
    return JsonlStore(cfg.profile_changes(), decode)
