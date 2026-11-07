"""The profile-change audit, through the shared atomic JSONL appender."""
from tlkernel import wire
from tlkernel.paths import ConfigDir
from tlkernel.profile_changes import ProfileChange
from tlkernel.stores import JsonlStore


def decode(data: object) -> ProfileChange:
    return wire.load(ProfileChange, data)


def profile_changes(cfg: ConfigDir) -> JsonlStore[ProfileChange]:
    return JsonlStore(cfg.profile_changes(), decode)
