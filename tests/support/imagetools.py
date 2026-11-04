"""No image tool (sips, ImageMagick) on the PATH, as on Linux: a picture is copied plain and no real process runs."""

import shutil
from unittest import mock

IMAGE_TOOLS = {"sips", "magick", "convert"}


def without_image_tools():
    """A patch (not started) of looks' `which` that hides the image tools and passes every other name to the `which` in force now."""
    inner = shutil.which

    def which(name, **kw):
        return None if name in IMAGE_TOOLS else inner(name, **kw)

    return mock.patch("taskloop.adapters.looks.shutil.which", which)
