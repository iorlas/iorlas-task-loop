"""bd's mise shim trusts only the requested working directory in its child environment."""
from pathlib import Path

import pytest

from tlkernel.env import bd_env


@pytest.mark.parametrize("trusted", ["", "/existing:/another"])
def test_bd_env_appends_cwd_without_changing_parent(trusted):
    base = {"PATH": "/bin", "MISE_TRUSTED_CONFIG_PATHS": trusted}
    out = bd_env("/x", base)
    assert out == {"PATH": "/bin", "MISE_TRUSTED_CONFIG_PATHS": ":".join(filter(None, (trusted, "/x")))}
    assert base == {"PATH": "/bin", "MISE_TRUSTED_CONFIG_PATHS": trusted}


def test_bd_env_defaults_to_current_directory():
    assert bd_env(None, {}) == {"MISE_TRUSTED_CONFIG_PATHS": str(Path.cwd())}
