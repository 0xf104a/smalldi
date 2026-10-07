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

    `get_instance()` creates the instance on the first call and returns it
    afterwards. A singleton overridden by another registered singleton
    (`delegate_to()`) never creates an instance of its own: it returns the
    instance of the overriding `LazySingleton`, so the target and the override
    share one instance.

    Overrides are not transitive: a singleton may be overridden only once, an
    override can't be overridden itself, and a singleton which is already
    overridden can't become an override of another one.

    A `LazySingleton` is frozen once it was asked for an instance, even if
    creating the instance then failed. A frozen singleton can't be overridden
    anymore, so every caller keeps receiving the same instance.

    :ivar _cls: the registered class
    """

    # _cls may None for interfaces, e.g. only override was imported
    def __init__(self, cls: Type | None, override: Type | None = None):
        """
        :param cls: registered class to create the instance of
        :param override: class instantiated instead of `cls`; used by interfaces
        """
        self._cls = cls
        self._override: Type | None = override
        self._delegate: "LazySingleton | None" = None
        self._is_override = False
        self._instance: Any = None
        self._frozen = False
        self._threads = AtomicSet()
        self.__instance_mutex__ = threading.RLock()

    def __repr__(self) -> str:
        return f"<LazySingleton of {self._cls}>"

    @property
    def _name(self) -> str:
        return getattr(self._cls, "__name__", repr(self._cls))

    def get_instance(self) -> Any:
        """
        Returns the instance: the overriding singleton's if overridden,
        otherwise its own, created on the first call. Freezes the singleton.

        :return: the instance
        """
        with self.__instance_mutex__:
            self._frozen = True
            if self._delegate is not None:
                return self._delegate.get_instance()
            ident = threading.current_thread().ident
            if ident is None:
                raise RuntimeError("Can not identify thread")
            was_in_our_path = self._threads.check_and_add(ident)
            if was_in_our_path:
                raise RuntimeError(
                    f"Singleton {self._name} re-entered itself during instantiation: likely circular dependency")
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
            raise SingletonFrozenError(f"Singleton {self._name} was already frozen")
        if self._override is not None or self._delegate is not None:
            raise RuntimeError(f"Singleton {self._name} was already overridden")
        self._override = new

    @threadsafe
    def delegate_to(self, target: "LazySingleton") -> None:
        """
        Overrides this singleton with another registered singleton: from now on
        `get_instance()` returns the target's instance.

        :param target: `LazySingleton` of the overriding class
        :raises TypeError: if `target` is this singleton, or the override would form a chain
        :raises SingletonFrozenError: if this singleton is already frozen
        :raises RuntimeError: if this singleton is already overridden
        """
        if target is self:
            raise TypeError(f"Singleton {self._name} can't override itself")
        if self._frozen:
            raise SingletonFrozenError(f"Singleton {self._name} was already frozen")
        if self._override is not None or self._delegate is not None:
            raise RuntimeError(f"Singleton {self._name} was already overridden")
        if self._is_override:
            raise TypeError(f"Singleton {self._name} is an override itself and can't be overridden")
        target._mark_as_override()
        self._delegate = target

    @threadsafe
    def _mark_as_override(self) -> None:
        """
        Marks this singleton as an override of another one.

        :raises TypeError: if this singleton is overridden itself
        """
        if self._override is not None or self._delegate is not None:
            raise TypeError(f"Singleton {self._name} is overridden and can't be an override")
        self._is_override = True

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
        if self._frozen:
            raise SingletonFrozenError(f"Singleton {self._name} was already frozen")
        if self._cls is not None:
            raise TypeError(f"Singleton {self._name} can not change its base implementation")
        self._cls = implementation_cls

    @property
    @threadsafe
    def frozen(self) -> bool:
        """
        Whether an instance was already requested, so the singleton can no
        longer be overridden.
        """
        return self._frozen