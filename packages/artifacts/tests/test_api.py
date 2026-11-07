"""The work stages get the original artifact operations through the public API."""
from tlartifacts import api, keep, store


def test_api_exports_the_work_operations():
    assert api.add is store.add
    assert api.run_listing is store.run_listing
    assert api.folder is store.folder
    assert api.listing is store.listing
    assert api.Keeper is keep.Keeper
    assert set(api.__all__) == {"add", "run_listing", "folder", "listing", "Keeper"}
    assert len(api.__all__) == 5
