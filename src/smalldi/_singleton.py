"""
Lazily instantiated singletons used by `Injector` to store registered classes.
"""
import threading
from typing import Any, Type

from smalldi.atomic import AtomicSet
from smalldi.concurrency import threadsafe


class SingletonFrozenError(Exception):
    """
    Raised on an attempt to override a singleton or an interface which was
    already injected (frozen).
    """
    pass


class LazySingleton:
    """
    Lazily created single instance of a class.

    `get_instance()` creates the instance on the first call, by calling `cls`
    or the `factory` given instead, and returns it afterwards. If `override()`
    was called, the instance of the overriding `LazySingleton` is returned
    instead and nothing is created. Overrides delegate to another `LazySingleton` rather than to
    a class, so everything resolving to the same singleton shares one
    instance, and an override of the override is followed transitively.

    A `LazySingleton` is frozen once it was asked for an instance, even if
    creating the instance then failed. A frozen singleton can't be overridden
    anymore, so every caller keeps receiving the same instance.

    Thread safety: bindings are guarded by the shared `atomic()` lock, held
    only briefly. Instance creation is guarded by a separate per-singleton
    lock, so concurrent first calls create exactly one instance.

    :ivar _cls: the registered class
    """

    # _cls may None for interfaces, e.g. only override was imported
    def __init__(self, cls: Type | None, override: Type | None = None):
        """
        :param cls: registered class to create the instance of
        :param factory: called instead of `_cls` to create the instance, if given
        """
        self._cls = cls
        self._override: Type[cls] | None = override
        self._instance: Any = None
        self._frozen = False
        self._threads = AtomicSet[int]()

    def __repr__(self) -> str:
        return f"<LazySingleton of {self._cls}>"

    @property
    @threadsafe
    def frozen(self) -> bool:
        """
        Whether an instance was already requested, so the singleton can no
        longer be overridden.
        """
        return self._frozen

    @threadsafe
    def get_instance(self) -> Any:
        """
        Returns the instance: the override's if set, otherwise its own,
        created on the first call. Freezes the singleton.

        Thread-safe: concurrent first calls create exactly one instance.

        :return: the instance
        """
        ident = threading.current_thread().ident
        if ident is None:
            raise RuntimeError("Can not identify thread")
        was_in_our_path = self._threads.check_and_add(ident)
        if was_in_our_path:
            raise RuntimeError(
                f"Singleton {self._cls.__name__} re-entered itself during instantiation: likely circular dependency")
        self._frozen = True
        if self._instance is None:
            try:
                if self._override is not None:
                    self._instance = self._override()
                else:
                    self._instance = self._cls()
            except BaseException:
                self._threads.remove(ident)
                raise
        self._threads.remove(ident)
        return self._instance

    @threadsafe
    def override(self, new: Type):
        if self._frozen:
            raise RuntimeError(f"Singleton {self._cls.__name__} was already frozen")
        if self._override is not None:
            raise RuntimeError(f"Singleton {self._cls.__name__} was already overridden")
        self._override = new

    @property
    @threadsafe
    def override_cls(self) -> Type | None:
        return self._override

    @property
    @threadsafe
    def implementation_cls(self) -> Type | None:
        return self._override

    @threadsafe
    def set_base(self, implementation_cls):
        self._cls = implementation_cls
