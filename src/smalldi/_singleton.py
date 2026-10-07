"""
Lazily instantiated singletons, one per class registered with `Injector`.
"""
import threading
from typing import Any, Type

from smalldi.atomic import AtomicSet
from smalldi.concurrency import threadsafe


class SingletonFrozenError(Exception):
    """
    Raised on an attempt to rebind a singleton or an interface which is frozen.

    A singleton is frozen once `LazySingleton.get_instance()` was called on it, an
    interface once an instance was requested through it. The attempt may be an
    override, an implementation of an interface without override, or
    `LazySingleton.set_base()`.
    """
    pass


class LazySingleton:
    """
    Lazily created single instance of a class, with an optional delegation to another singleton.

    `get_instance()` creates the instance on the first call and returns it
    afterwards. A singleton overridden by another registered singleton
    (`delegate_to()`) never creates an instance of its own: it returns the
    instance of the overriding `LazySingleton`, so the target and the override
    share one instance.

    Overrides are not transitive: a singleton may delegate only once, a
    singleton that is an override can't be overridden itself, and a singleton
    which already delegates can't become an override of another one.

    A `LazySingleton` is frozen once an instance was requested from it, even
    if creating the instance then failed. A frozen singleton can't be
    overridden anymore. A failed construction leaves no instance behind, so
    the next `get_instance()` call runs the constructor again.

    Every method takes the reentrant lock `__instance_mutex__` of the instance
    for the duration of the call: `get_instance()` explicitly, the others
    through `@threadsafe`. The lock is held while the constructor runs.

    :ivar _cls: the registered class, called to create the instance
    :ivar _override: class called instead of `_cls`, set by `override()`; `Injector` never sets it
    :ivar _delegate: `LazySingleton` whose instance is returned instead of creating one
    :ivar _is_override: whether this singleton overrides another singleton or an interface
    :ivar _instance: the created instance, or None
    :ivar _frozen: whether an instance was requested already
    :ivar _threads: idents of the threads currently inside the constructor
    :ivar __instance_mutex__: the lock guarding every method
    """

    # _cls may None for interfaces, e.g. only override was imported
    def __init__(self, cls: Type | None, override: Type | None = None):
        """
        :param cls: registered class to create the instance of; `Injector` always passes it
        :param override: class instantiated instead of `cls`; `Injector` never passes it
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
        """
        :return: `<LazySingleton of {class}>`
        """
        return f"<LazySingleton of {self._cls}>"

    @property
    def _name(self) -> str:
        """
        :return: name of the registered class, or its repr if it has no name
        """
        return getattr(self._cls, "__name__", repr(self._cls))

    def get_instance(self) -> Any:
        """
        Returns the instance, creating it on the first call, and freezes the singleton.

        If the singleton delegates to an override, the override's `get_instance()`
        is returned, which freezes the override too. Otherwise the instance is
        created by calling `_override` if set, else `_cls`, while the calling
        thread's ident is recorded in `_threads`: a nested call from the same
        thread, which happens when the constructor depends on this singleton
        directly or through other singletons, is a circular dependency. The
        singleton is frozen before anything else happens, so it stays frozen if
        the constructor raises. The instance lock is held throughout, so another
        thread asking for the instance waits for the constructor to finish.

        :return: the instance
        :raises RuntimeError: if the current thread has no ident
        :raises RuntimeError: if the calling thread is already inside this singleton's constructor
            (circular dependency)
        :raises Exception: any exception raised by the constructor propagates unchanged
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
        """
        Makes `get_instance()` call `new` instead of the registered class. Not used by `Injector`.

        `new` is not validated against the registered class.

        :param new: class to instantiate instead of `_cls`
        :raises SingletonFrozenError: if this singleton is frozen
        :raises RuntimeError: if this singleton already has an override class or delegates
        """
        if self._frozen:
            raise SingletonFrozenError(f"Singleton {self._name} was already frozen")
        if self._override is not None or self._delegate is not None:
            raise RuntimeError(f"Singleton {self._name} was already overridden")
        self._override = new

    @threadsafe
    def delegate_to(self, target: "LazySingleton") -> None:
        """
        Overrides this singleton with another registered singleton: afterwards
        `get_instance()` returns the target's instance.

        All checks run before anything changes. The target is marked as an
        override, which fails if the target delegates or has an override class
        itself; the target may be frozen already, its instance is then shared.
        This singleton's lock is held for the call, and the target's lock is taken
        while it is marked.

        :param target: `LazySingleton` of the overriding class
        :raises TypeError: if `target` is this singleton
        :raises SingletonFrozenError: if this singleton is frozen
        :raises RuntimeError: if this singleton already delegates or has an override class
        :raises TypeError: if this singleton is an override itself, or `target` already delegates
            or has an override class (the override would form a chain)
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
        Marks this singleton as an override of another singleton or of an interface.

        A frozen singleton may be marked: its existing instance is then shared
        with the target.

        :raises TypeError: if this singleton delegates or has an override class
        """
        if self._override is not None or self._delegate is not None:
            raise TypeError(f"Singleton {self._name} is overridden and can't be an override")
        self._is_override = True

    @property
    @threadsafe
    def override_cls(self) -> Type | None:
        """
        The class set with `override()`, or None. Not used by `Injector`.
        """
        return self._override

    @property
    @threadsafe
    def implementation_cls(self) -> Type | None:
        """
        The class set with `override()`, or None; the same value as `override_cls`. Not used by `Injector`.
        """
        return self._override

    @threadsafe
    def set_base(self, implementation_cls):
        """
        Sets the registered class of a singleton created without one. Not used by `Injector`.

        :param implementation_cls: class to create the instance of
        :raises SingletonFrozenError: if this singleton is frozen
        :raises TypeError: if this singleton already has a class
        """
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
        longer be overridden. Not used by `Injector`.
        """
        return self._frozen