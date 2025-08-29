def staticclass(cls):
    """
    Marks class as static. Static classes can't be instantiated.
    """
    def _no_init(*_args, **_kwargs):
        raise TypeError("Can't instantiate static class")
    cls.__init__ = _no_init
    return cls