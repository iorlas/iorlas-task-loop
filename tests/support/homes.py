"""The config dir and Claude's dir a test's code uses, read from the environment the test set up (HOME, XDG_CONFIG_HOME, CLAUDE_CONFIG_DIR)
the way the edge reads it: a snapshot taken now, so a test that patches the environment first sees its own dirs."""
from pathlib import Path

from taskloop.adapters import ident
from taskloop.contracts.env import snapshot
from taskloop.contracts.paths import ConfigDir


def config_dir() -> Path:
    return ident.config_dir(snapshot())


def claude_dir() -> Path:
    return ident.claude_dir(snapshot())


def cfg() -> ConfigDir:
    return ConfigDir(config_dir())
