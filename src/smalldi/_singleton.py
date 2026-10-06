from typing import Optional

from smalldi._interface import InterfaceTable, InterfaceAlreadyBoundError
from smalldi.threading import threadsafe


class SingletonFrozenError(Exception):
    """The singleton was already injected; it can no longer be overridden."""

    def __init__(self, singleton_cls, override_cls):
        super().__init__(f"Cannot override singleton {singleton_cls!r} with {override_cls!r}: "
                         f"{singleton_cls!r} was already injected")
        self.singleton_cls = singleton_cls
        self.override_cls = override_cls


@threadsafe
class LazySingleton:
    """
    A singleton that is created on first access.
    It may be overridden with another lazy singleton of a subclass until it is created;
    after that it is frozen and get() returns the overriding singleton's instance.
    If the created instance has `_on_singleton_created` method, it is called right after creation.
    """
    def __init__(self, cls: type):
        self.cls = cls
        self._override: Optional["LazySingleton"] = None
        self._creating = False
        cls.__singleton__ = None
        self.instance = None

    def get(self):
        """
        Returns the instance, creating it (or the overriding singleton's instance) on first call.
        :return: singleton instance
        :raises TypeError: on circular dependency
        """
        if self.instance is not None:
            return self.instance
        if self._creating:
            raise TypeError(f"Circular dependency while creating singleton {self.cls!r}")
        self._creating = True
        try:
            if self._override is not None:
                self.instance = self._override.get()
            else:
                self.instance = self.cls()
        finally:
            self._creating = False
        self.cls.__singleton__ = self.instance
        if self._override is None:
            on_created = getattr(self.instance, "_on_singleton_created", None)
            if on_created is not None:
                on_created()
        return self.instance

    def override(self, new: "LazySingleton") -> None:
        """
        Makes get() return the instance of another lazy singleton.
        :param new: lazy singleton of a concrete subclass
        :raises TypeError: if new.cls is not a concrete subclass
        :raises InterfaceAlreadyBoundError: if already overridden with another singleton
        :raises SingletonFrozenError: if the instance was already created
        """
        InterfaceTable.check_impl(self.cls, new.cls)
        if self._override is new:
            return
        if self._override is not None:
            raise InterfaceAlreadyBoundError(self.cls, self._override.cls, new.cls, "override")
        if self.frozen:
            raise SingletonFrozenError(self.cls, new.cls)
        self._override = new

    @property
    def overridden(self) -> bool:
        return self._override is not None

    @property
    def frozen(self) -> bool:
        # Generally, if lazy singleton has instance, it means some dependent class already injected it
        return self.instance is not None or self._creating
