class SingletonFrozenError(Exception):
    """The singleton was already injected; it can no longer be overridden."""

    def __init__(self, singleton_cls, override_cls):
        super().__init__(f"Cannot override singleton {singleton_cls!r} with {override_cls!r}: "
                         f"{singleton_cls!r} was already injected")
        self.singleton_cls = singleton_cls
        self.override_cls = override_cls
