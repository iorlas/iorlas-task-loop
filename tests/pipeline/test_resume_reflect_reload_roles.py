"""The remaining pipeline roles stay narrow and are resolved only when used."""
import inspect

import pytest

from taskloop.app.pipeline import reflect, reload, resume


@pytest.mark.parametrize("module", [resume, reflect, reload])
def test_role_protocols_have_at_most_sixteen_own_members(module):
    protocols = {name: value for name, value in vars(module).items()
                 if isinstance(value, type) and getattr(value, "_is_protocol", False)
                 and value.__module__ == module.__name__}
    assert protocols
    counts = {name: len(set(inspect.get_annotations(value)) | {
        key for key, member in vars(value).items()
        if isinstance(member, property) or (callable(member) and not key.startswith("_"))})
        for name, value in protocols.items()}
    assert {name: count for name, count in counts.items() if count > 16} == {}


@pytest.mark.parametrize("component", [resume.Resume, reflect.Reflector, reload.Reload])
def test_constructor_does_not_resolve_role_members(component):
    class LazyRole:
        def __getattribute__(self, name):
            raise AssertionError(f"constructor resolved {name}")

    parameters = inspect.signature(component).parameters
    component(*(LazyRole() for _ in parameters))
