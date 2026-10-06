"""
Lazily instantiated singletons used by `Injector` to store registered classes
and interfaces.
"""
import threading
from contextlib import AbstractContextManager
from inspect import isabstract
from typing import Any, Type


class SingletonFrozenError(Exception):
    """
    Raised on an attempt to override a singleton or an interface which was
    already injected (frozen).
    """


def _same_class(a: type, b: type) -> bool:
    """
    Whether two classes are the same class, or a reloaded version of it.

    :param a: first class
    :param b: second class
    :return: True if the classes are identical or share module and qualified name
    """
    return a is b or (a.__module__, a.__qualname__) == (b.__module__, b.__qualname__)


class LazySingleton:
    """
    Lazily resolved single instance of a class.

    A `LazySingleton` is created for every registered singleton class and for
    every interface. `get_instance()` returns, in order of precedence:

    1. the instance of the overriding `LazySingleton`, if `override()` was called;
    2. the instance of the implementing `LazySingleton`, if `implement()` was
       called (interfaces only);
    3. its own instance of `cls`, created on the first call. An abstract `cls`
       (an interface) is never instantiated: `NotImplementedError` is raised
       instead.

    Overriding and implementing delegate to another `LazySingleton` rather than
    to a class, so everything resolving to the same singleton shares one
    instance, and overrides of the delegate are followed transitively.

    A `LazySingleton` is frozen once it was asked for an instance, even if
    creating the instance then failed. A frozen singleton can't be overridden
    anymore, so every caller keeps receiving the same instance.

    Thread safety: the bindings (override, implementation, frozen flag) of all
    singletons are guarded by one shared lock, held only briefly and never
    while an instance is being created. Use `LazySingleton.atomic()` to check
    and change several singletons as one step. Instance creation is guarded by
    a separate per-singleton lock, so concurrent first calls create exactly one
    instance, and constructors may freely use the injector.

    :ivar cls: the registered class or interface
    """
    _state_lock = threading.RLock()

    def __init__(self, cls: Type):
        """
        :param cls: registered class or interface to resolve the instance of
        """
        self.cls = cls
        self._override: LazySingleton | None = None
        self._implementation: LazySingleton | None = None
        self._instance: Any = None
        self._frozen = False
        self._build_lock = threading.RLock()

    def __repr__(self) -> str:
        return f"<LazySingleton of {self.cls!r}>"

    @classmethod
    def atomic(cls) -> AbstractContextManager:
        """
        Returns the lock guarding the bindings of all singletons, to check and
        change several of them without another thread freezing or rebinding
        one in between. Reentrant. Don't create instances while holding it.

        :return: context manager holding the lock
        """
        return cls._state_lock

    @property
    def override_singleton(self) -> "LazySingleton | None":
        """
        The singleton injected instead of this one, or None if not overridden.
        """
        return self._override

    @property
    def implementation(self) -> "LazySingleton | None":
        """
        The singleton implementing this interface, or None if not implemented.
        """
        return self._implementation

    @property
    def frozen(self) -> bool:
        """
        Whether an instance was already requested, so the singleton can no
        longer be overridden.
        """
        return self._frozen

    @property
    def resolvable(self) -> bool:
        """
        Whether `get_instance()` can return an instance: the singleton is
        overridden, implemented, or `cls` is concrete.
        """
        return self._override is not None or self._implementation is not None or not isabstract(self.cls)

    def get_instance(self) -> Any:
        """
        Returns the instance: the override's if set, otherwise the
        implementation's, otherwise its own instance of `cls`, created on the
        first call. Freezes the singleton.

        Thread-safe: concurrent first calls create exactly one instance.

        :return: the instance
        :raises NotImplementedError: if `cls` is an interface which is neither
            overridden nor implemented
        """
        with self._state_lock:
            delegate = self._override or self._implementation
            if delegate is None and isabstract(self.cls):
                raise NotImplementedError(f"Interface {self.cls!r} is not implemented")
            self._frozen = True
        if delegate is not None:
            return delegate.get_instance()
        with self._build_lock:
            if self._instance is None:
                self._instance = self.cls()
            return self._instance

    def check_override(self, override: "LazySingleton"):
        """
        Checks that `override()` would succeed, without changing anything.

        :param override: singleton to inject instead of this one
        :raises TypeError: if `override` is this singleton, its class isn't a
            subclass of `cls`, a different override is already set, or the
            override would form a cycle
        :raises SingletonFrozenError: if this singleton is frozen and not
            overridden yet
        """
        with self._state_lock:
            if override is self or override.cls is self.cls:
                raise TypeError(f"Class {self.cls} cannot override itself")
            if not issubclass(override.cls, self.cls):
                raise TypeError(f"Class {override.cls} is not a subclass of {self.cls}")
            if self._override is not None:
                if not _same_class(self._override.cls, override.cls):
                    raise TypeError(f"{self.cls} is already overridden by {self._override.cls}")
            elif self._frozen:
                raise SingletonFrozenError(
                    f"{self.cls} was already injected and cannot be overridden"
                )
            if override._delegates_to(self):
                raise TypeError(f"Overriding {self.cls} with {override.cls} would form a cycle")

    def override(self, override: "LazySingleton"):
        """
        Makes `get_instance()` return the instance of `override` instead,
        taking precedence over any implementation. Overriding again with the
        same class (or a reloaded version of it) rebinds the override.

        :param override: singleton to inject instead of this one
        :raises TypeError: see `check_override`
        :raises SingletonFrozenError: see `check_override`
        """
        with self._state_lock:
            self.check_override(override)
            self._override = override

    def check_implementation(self, implementation: "LazySingleton"):
        """
        Checks that `implement()` would succeed, without changing anything.

        :param implementation: singleton implementing this interface
        :raises TypeError: if `cls` isn't abstract, the implementation's class
            isn't a subclass of `cls`, or a different implementation is already set
        """
        with self._state_lock:
            if not isabstract(self.cls):
                raise TypeError(f"Class {self.cls} is not an interface")
            if not issubclass(implementation.cls, self.cls):
                raise TypeError(f"Class {implementation.cls} is not a subclass of {self.cls}")
            if self._implementation is not None and not _same_class(self._implementation.cls, implementation.cls):
                raise TypeError(
                    f"Interface {self.cls} is already implemented by {self._implementation.cls}; "
                    f"use @Injector.override to replace it"
                )

    def implement(self, implementation: "LazySingleton"):
        """
        Makes `get_instance()` of this interface return the instance of
        `implementation`, unless overridden. Implementing again with the same
        class (or a reloaded version of it) rebinds the implementation. Allowed
        after freezing: an override, if any, still wins, and a different
        implementation is refused anyway.

        :param implementation: singleton implementing this interface
        :raises TypeError: see `check_implementation`
        """
        with self._state_lock:
            self.check_implementation(implementation)
            self._implementation = implementation

    def retarget(self, old: "LazySingleton", new: "LazySingleton"):
        """
        Replaces references to `old` with `new` in the override and
        implementation of this singleton, bypassing all checks. Used when a
        singleton is registered again, so bindings follow the new registration.

        :param old: replaced singleton
        :param new: singleton replacing it
        """
        with self._state_lock:
            if self._override is old:
                self._override = new
            if self._implementation is old:
                self._implementation = new

    def inherit_override(self, old: "LazySingleton"):
        """
        Takes over the override of `old`, bypassing all checks. Used when a
        singleton is registered again, so it stays overridden.

        :param old: previous registration of the same class
        """
        with self._state_lock:
            self._override = old._override

    def _delegates_to(self, target: "LazySingleton") -> bool:
        """
        Whether `get_instance()` would reach `target` through overrides and
        implementations. Must be called while holding the state lock.

        :param target: singleton to look for
        :return: True if `target` is this singleton or one it delegates to
        """
        seen = set()
        pending = [self]
        while pending:
            current = pending.pop()
            if current is target:
                return True
            if id(current) in seen:
                continue
            seen.add(id(current))
            pending.extend(d for d in (current._override, current._implementation) if d is not None)
        return False
