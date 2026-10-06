"""
Lazily instantiated singletons used by `Injector` to store registered classes.
"""
import threading
from contextlib import AbstractContextManager
from typing import Any, Callable, Type


class SingletonFrozenError(Exception):
    """
    Raised on an attempt to override a singleton or an interface which was
    already injected (frozen).
    """


# Guards the bindings (overrides, implementations, frozen flags) of every
# singleton and interface; `Injector` uses it for its registry too. Held only
# briefly, never while an instance is being created, so constructors may
# freely use the injector.
_bindings_lock = threading.RLock()


def atomic() -> AbstractContextManager:
    """
    Returns the lock guarding the bindings of all singletons and interfaces,
    to check and change several of them without another thread freezing or
    rebinding one in between. Reentrant. Don't create instances while holding it.

    :return: context manager holding the lock
    """
    return _bindings_lock


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

    :ivar cls: the registered class
    """
    def __init__(self, cls: Type, factory: Callable[[], Any] | None = None):
        """
        :param cls: registered class to create the instance of
        :param factory: called instead of `cls` to create the instance, if given
        """
        self.cls = cls
        self._factory = factory if factory is not None else cls
        self._override: LazySingleton | None = None
        self._instance: Any = None
        self._frozen = False
        self._build_lock = threading.RLock()

    def __repr__(self) -> str:
        return f"<LazySingleton of {self.cls!r}>"

    @property
    def override_singleton(self) -> "LazySingleton | None":
        """
        The singleton injected instead of this one, or None if not overridden.
        """
        return self._override

    @property
    def frozen(self) -> bool:
        """
        Whether an instance was already requested, so the singleton can no
        longer be overridden.
        """
        return self._frozen

    def get_instance(self) -> Any:
        """
        Returns the instance: the override's if set, otherwise its own,
        created on the first call. Freezes the singleton.

        Thread-safe: concurrent first calls create exactly one instance.

        :return: the instance
        """
        with _bindings_lock:
            override = self._override
            self._frozen = True
        if override is not None:
            return override.get_instance()
        with self._build_lock:
            if self._instance is None:
                self._instance = self._factory()
            return self._instance

    def check_override(self, override: "LazySingleton"):
        """
        Checks that `override()` would succeed, without changing anything.
        Repeating the current override is a no-op and always passes.

        :param override: singleton to inject instead of this one
        :raises TypeError: if `override` is this singleton, its class isn't a
            subclass of `cls`, another override is already set, or the
            override would form a cycle
        :raises SingletonFrozenError: if this singleton is frozen
        """
        with _bindings_lock:
            if override is self or override.cls is self.cls:
                raise TypeError(f"Class {self.cls} cannot override itself")
            if not issubclass(override.cls, self.cls):
                raise TypeError(f"Class {override.cls} is not a subclass of {self.cls}")
            if override is self._override:
                return
            if self._frozen:
                raise SingletonFrozenError(
                    f"{self.cls} was already injected and cannot be overridden"
                )
            if self._override is not None:
                raise TypeError(f"{self.cls} is already overridden by {self._override.cls}")
            if override._overrides_chain_to(self):
                raise TypeError(f"Overriding {self.cls} with {override.cls} would form a cycle")

    def override(self, override: "LazySingleton"):
        """
        Makes `get_instance()` return the instance of `override` instead.
        Repeating the current override is a no-op.

        :param override: singleton to inject instead of this one
        :raises TypeError: see `check_override`
        :raises SingletonFrozenError: see `check_override`
        """
        with _bindings_lock:
            self.check_override(override)
            self._override = override

    def _overrides_chain_to(self, target: "LazySingleton") -> bool:
        """
        Whether `get_instance()` would reach `target` through overrides.
        Must be called while holding the bindings lock.

        :param target: singleton to look for
        :return: True if `target` is this singleton or one it delegates to
        """
        current: LazySingleton | None = self
        while current is not None:
            if current is target:
                return True
            current = current._override
        return False
