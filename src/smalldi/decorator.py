"""
Class decorators.
"""


def staticclass(cls):
    """
    Marks a class as static: instantiating it raises `TypeError`.

    The class's `__init__` is replaced by a function that raises, so an
    existing `__init__` is discarded and subclasses inherit the raising one.
    Class attributes, class methods and static methods are unaffected.

    :param cls: class to mark
    :return: `cls`, with its `__init__` replaced
    """
    def _no_init(*_args, **_kwargs):
        raise TypeError("Can't instantiate static class")
    cls.__init__ = _no_init
    return cls
