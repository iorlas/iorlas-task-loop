"""A bag of attributes standing in for an argparse namespace in tests."""


class Args:
    def __init__(self, **kw: object) -> None:
        self.__dict__.update(kw)
