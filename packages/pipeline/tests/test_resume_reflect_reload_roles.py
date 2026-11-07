"""The remaining pipeline roles stay narrow and are resolved only when used."""
import inspect

import pytest

from tlpipeline import journal, reflect, reload, resume


@pytest.mark.parametrize("component", [resume.Resume, reflect.Reflector, reload.Reload, journal.Journal])
def test_constructor_does_not_resolve_role_members(component):
    class LazyRole:
        def __getattribute__(self, name):
            raise AssertionError(f"constructor resolved {name}")

    parameters = inspect.signature(component).parameters
    component(*(LazyRole() for _ in parameters))
