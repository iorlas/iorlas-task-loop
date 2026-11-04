"""A class whose tests print into a buffer made in setup_method."""
import contextlib
import functools


def stdout_in(attr):
    """Class decorator: each test the class defines runs with sys.stdout going to `self.<attr>`. pytest swaps sys.stdout at the start of
    every phase, so a redirect made in setup_method would not reach the test."""
    def wrap(cls):
        for name, fn in list(vars(cls).items()):
            if name.startswith("test") and callable(fn):
                setattr(cls, name, _around(fn, attr))
        return cls
    return wrap


def _around(fn, attr):
    @functools.wraps(fn)
    def run(self, *args, **kwargs):
        with contextlib.redirect_stdout(getattr(self, attr)):
            return fn(self, *args, **kwargs)
    return run
