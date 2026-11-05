"""any-plugin-cache: installed Claude Code plugin versions, pins and rollback, and a format-preserving version bump. Stdlib only."""

from any_plugin_cache.installs import behind, installed_version, installs, previous, rollback_target, version_key
from any_plugin_cache.jsonver import NoVersionError, entry_offset, set_json_version

__all__ = [
    "NoVersionError",
    "behind",
    "entry_offset",
    "installed_version",
    "installs",
    "previous",
    "rollback_target",
    "set_json_version",
    "version_key",
]
