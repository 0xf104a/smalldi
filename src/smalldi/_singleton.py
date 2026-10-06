"""
Lazily instantiated singletons used by `Injector` to store registered classes.
"""
from typing import Any, Type

from smalldi.concurrency import threadsafe


class SingletonFrozenError(Exception):
    """
    Raised on an attempt to override a singleton which was already
    instantiated (frozen).
    """

class LazySingleton:
    """
    Holder of a single, lazily created instance of a class.

    The instance is created on the first `get_instance()` call. Until then the
    class may be replaced with a subclass through `override()`. Once the
    instance exists, the singleton is frozen and further overrides raise
    `SingletonFrozenError`.

    `get_instance()` and `override()` are thread-safe; the attributes aren't
    meant to be modified directly.

    :ivar cls: the registered class
    :ivar override_cls: subclass of `cls` to instantiate instead of it, or None
    :ivar instance: the created instance, or None if it wasn't created yet
    """
    def __init__(self, cls: Type, override: Type | None):
        """
        :param cls: class to hold the singleton instance of
        :param override: subclass of `cls` to instantiate instead of it,
            or None to instantiate `cls` itself
        :raises TypeError: if `override` isn't a subclass of `cls`
        """
        self.cls = cls
        self.override_cls = None
        self.instance = None
        if override is not None:
            self._validate_override(cls, override)
        self.override_cls = override

    def _validate_override(self, base: Type, override: Type):
        """
        Checks that `base` may be overridden with `override`.
        Overriding a class with itself is always allowed.

        :param base: class being overridden
        :param override: class to override it with
        :raises SingletonFrozenError: if the instance was already created
        :raises TypeError: if `override` isn't a subclass of `base`
        """
        if base is override:
            return
        if self.frozen:
            raise SingletonFrozenError("Cannot override a frozen singleton")
        if not issubclass(override, base):
            raise TypeError(f"Override {override} is not a subclass of {base}")

    @threadsafe
    def get_instance(self) -> Any:
        """
        Returns the singleton instance, creating it on the first call.
        The override class is instantiated if one is set, the registered class
        otherwise. Creating the instance freezes the singleton.

        Thread-safe: concurrent first calls create exactly one instance.

        :return: the singleton instance
        """
        if self.instance is None:
            if self.override_cls is not None:
                self.instance = self.override_cls()
            else:
                self.instance = self.cls()
        return self.instance

    @threadsafe
    def override(self, override: Type):
        """
        Makes the singleton instantiate `override` instead of the registered class.
        Repeating the same override is a no-op.

        :param override: subclass of the registered class
        :raises TypeError: if a different override is already set,
            or `override` isn't a subclass of the registered class
        :raises SingletonFrozenError: if the instance was already created
        """
        if self.override_cls is override:
            return
        if self.override_cls is not None:
            raise TypeError("Cannot override an already overridden singleton")
        self._validate_override(self.cls, override)
        self.override_cls = override

    @property
    def frozen(self) -> bool:
        """
        Whether the instance was already created, so the singleton can no
        longer be overridden.
        """
        return self.instance is not None

