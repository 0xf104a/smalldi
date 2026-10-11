"""
Lazily instantiated singletons, one per registered class or per overridden class and its override.
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
    Lazily created single instance of a registered class, or of the class overriding it.

    `get_instance()` creates the instance on the first call and returns it
    afterwards, calling the override class if one was set with `override()`,
    else the registered class. An overridden class and its override share one
    `LazySingleton`: `Injector` keeps the object under both classes, so both
    resolve to one instance and the overridden class is never instantiated.

    Overrides are not transitive: a singleton is overridden at most once, a
    singleton that is an override can't be overridden itself, and a singleton
    which is overridden can't become an override.

    A `LazySingleton` is frozen once an instance was requested from it, even
    if creating the instance then failed. `Injector` freezes it with
    `_freeze()` while it looks it up, under its class mutex, so the request
    and the freeze are one step for every concurrent override. A frozen
    singleton can't be overridden anymore, and a frozen singleton without an
    instance, whose constructor is running or failed, can't become an
    override. A failed construction leaves no instance behind, so the next
    `get_instance()` call runs the constructor again.

    Two reentrant locks guard a `LazySingleton`. The state lock
    `__instance_mutex__` guards the bindings and the frozen flag; every method
    except `get_instance()` holds it for the whole call through `@threadsafe`,
    and `get_instance()` holds it only to freeze the singleton. It is never
    held while a constructor runs or while another singleton is asked for its
    instance. The build lock `_build_lock` is held while the constructor runs,
    so concurrent first calls create exactly one instance; nothing else takes it.

    :ivar _cls: the registered class, called to create the instance unless overridden
    :ivar _override: class called instead of `_cls`, set by `override()`, or None
    :ivar _is_override: whether this singleton is an override of another singleton or of an interface
    :ivar _instance: the created instance, or None
    :ivar _frozen: whether an instance was requested already
    :ivar _threads: idents of the threads currently inside the constructor
    :ivar __instance_mutex__: the state lock
    :ivar _build_lock: the lock held while the constructor runs
    """

    # _cls may None for interfaces, e.g. only override was imported
    def __init__(self, cls: Type | None = None, override: Type | None = None):
        """
        :param cls: registered class to create the instance of; `Injector` always passes it
        :param override: class instantiated instead of `cls`; `Injector` sets it through `override()`
        """
        self._cls = cls
        self._override: Type | None = override
        self._is_override = False
        self._instance: Any = None
        self._frozen = False
        self._threads: AtomicSet[int] = AtomicSet()
        self.__instance_mutex__ = threading.RLock()
        self._build_lock = threading.RLock()

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

    @threadsafe
    def _freeze(self) -> None:
        """
        Freezes the singleton without requesting its instance.

        `Injector` calls it under its class mutex while it looks the singleton
        up, before `get_instance()` is called outside that mutex.
        """
        self._frozen = True

    def get_instance(self) -> Any:
        """
        Returns the instance, creating it on the first call, and freezes the singleton.

        The singleton is frozen first, under the state lock, so it stays frozen
        if the constructor raises, and an override attempted while the
        constructor runs fails with `SingletonFrozenError`. The instance is
        created under the build lock by calling `_override` if set, else
        `_cls`, while the calling thread's ident is recorded in `_threads`: a
        nested call from the same thread, which happens when the constructor
        depends on this singleton directly or through other singletons, is a
        circular dependency. Another thread asking for the instance waits on
        the build lock until the constructor finishes.

        :return: the instance
        :raises RuntimeError: if the current thread has no ident
        :raises RuntimeError: if the calling thread is already inside this singleton's constructor
            (circular dependency)
        :raises Exception: any exception raised by the constructor propagates unchanged
        """
        with self.__instance_mutex__:
            self._frozen = True
        with self._build_lock:
            ident = threading.current_thread().ident
            if ident is None:
                raise RuntimeError("Can not identify thread")
            was_in_our_path = self._threads.check_and_add(ident)
            if was_in_our_path:
                raise RuntimeError(
                    f"Singleton {self._name} re-entered itself during instantiation: likely circular dependency")
            try:
                if self._instance is None:
                    if self._override is not None:
                        self._instance = self._override()
                    else:
                        if self._cls is None:
                            raise TypeError(f"Singleton {self._name} has no class to instantiate")
                        self._instance = self._cls()
                return self._instance
            finally:
                self._threads.remove(ident)

    @threadsafe
    def override(self, new: Type, previous: "LazySingleton | None" = None):
        """
        Makes `get_instance()` call `new` instead of the registered class, and marks
        this singleton as an override.

        All checks run before anything changes. `new` is not validated against
        the registered class: `Injector` checks that it is a registered subclass.
        If `previous`, the `LazySingleton` registered for `new` so far, is
        frozen and has an instance, this singleton becomes frozen and takes over
        that instance, so an instance of `new` created before the override is
        shared instead of being created again. If `previous` is frozen without
        an instance, because its constructor is running or failed, the override
        is refused: its constructor would otherwise run again in this singleton.
        `previous` is read under its own state lock; `Injector` then discards it
        and registers this singleton for `new`.

        :param new: class to instantiate instead of `_cls`
        :param previous: `LazySingleton` so far registered for `new`, or None
        :raises SingletonFrozenError: if this singleton is frozen, or `previous` is frozen and has
            no instance
        :raises RuntimeError: if this singleton already has an override class
        :raises TypeError: if this singleton is an override itself, or `new` is its registered class
        """
        if self._frozen:
            raise SingletonFrozenError(f"Singleton {self._name} was already frozen")
        if self._override is not None:
            raise RuntimeError(f"Singleton {self._name} was already overridden")
        if self._is_override:
            raise TypeError(f"Singleton {self._name} is an override itself and can't be overridden")
        if new is self._cls:
            raise TypeError(f"Singleton {self._name} can't override itself")
        frozen, instance = False, None
        if previous is not None:
            with previous.__instance_mutex__:
                frozen, instance = previous._frozen, previous._instance
        if frozen and instance is None:
            raise SingletonFrozenError(
                f"Singleton {getattr(new, '__name__', repr(new))} was already frozen and has no instance: "
                f"its constructor is running or failed")
        self._override = new
        self._is_override = True
        if frozen:
            self._frozen = True
            self._instance = instance

    @threadsafe
    def _mark_as_override(self, cls: Type) -> None:
        """
        Marks this singleton as the override of an interface, on behalf of `cls`.

        `cls` is the registered class of this singleton or, if the singleton is
        shared between an overridden class and its override, the override. A
        frozen singleton may be marked: its existing instance is then shared
        with the interface.

        :param cls: the class overriding the interface
        :raises TypeError: if `cls` is overridden by another class
        """
        if self._override is not None and self._override is not cls:
            raise TypeError(f"Singleton {cls.__name__} is overridden and can't be an override")
        self._is_override = True

    @property
    @threadsafe
    def override_cls(self) -> Type | None:
        """
        The class set with `override()`, or None.
        """
        return self._override

    @property
    @threadsafe
    def implementation_cls(self) -> Type | None:
        """
        The registered class, or None for a singleton created without one.
        """
        return self._cls

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

    @threadsafe
    def clone(self):
        clone = self.__class__(
            self._cls,
            self._override
        )
        clone._is_override = self._is_override
        return clone
