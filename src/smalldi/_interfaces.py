"""
Interfaces and the singletons implementing them, used by `Injector`.
"""
from inspect import isabstract
from typing import Any, Iterator, Type

from smalldi._singleton import LazySingleton, SingletonFrozenError, _bindings_lock


class LazyInterfaceImpl:
    """
    Binding of an interface to the singleton injected for it.

    An interface is an abstract class and is never instantiated itself.
    `get_instance()` returns the instance of the overriding singleton if the
    interface is overridden, otherwise the instance of the implementing one.
    Both are `LazySingleton`s, so the interface shares the instance with its
    implementation, and an overridden implementation is followed as well.

    Overriding and freezing are plain singleton management, so they are
    delegated to an inner `LazySingleton` of the interface whose instance is
    produced by the implementation. This class only adds what is specific to
    interfaces: abstractness, the implementation slot and `NotImplementedError`
    for an unbound interface.

    Nothing rebinds a frozen interface, except its first implementation when
    it is already overridden: the override keeps winning, so the injected
    instance doesn't change.

    :ivar interface: the abstract class
    """
    def __init__(self, interface: Type):
        """
        :param interface: abstract class to bind
        :raises TypeError: if `interface` isn't abstract
        """
        if not isabstract(interface):
            raise TypeError(f"Interface {interface.__name__!r} is not abstract")
        self.interface = interface
        self._implementation: LazySingleton | None = None
        self._singleton = LazySingleton(interface, factory=self._implementation_instance)

    def __repr__(self) -> str:
        return f"<LazyInterfaceImpl of {self.interface.__name__!r}>"

    def _implementation_instance(self) -> Any:
        """
        Factory of the inner singleton: the interface's own "instance" is the
        implementation's one. Only reached when the interface is implemented,
        since `get_instance` checks `resolvable` first and bindings are never unset.
        """
        return self._implementation.get_instance()

    @property
    def implementation(self) -> LazySingleton | None:
        """
        The singleton implementing the interface, or None if not implemented.
        """
        return self._implementation

    @property
    def override_singleton(self) -> LazySingleton | None:
        """
        The singleton injected instead of the implementation, or None if not overridden.
        """
        return self._singleton.override_singleton

    @property
    def frozen(self) -> bool:
        """
        Whether an instance was already requested, so the binding can no
        longer be changed.
        """
        return self._singleton.frozen

    @property
    def resolvable(self) -> bool:
        """
        Whether `get_instance()` can return an instance, i.e. the interface is
        implemented or overridden.
        """
        return self._singleton.override_singleton is not None or self._implementation is not None

    def get_instance(self) -> Any:
        """
        Returns the instance of the override if set, otherwise of the
        implementation. Freezes the binding. An unbound interface raises
        without freezing, so it may still be bound afterwards.

        :return: the instance
        :raises NotImplementedError: if the interface is neither implemented nor overridden
        """
        if not self.resolvable:
            raise NotImplementedError(f"Interface {self.interface.__name__!r} is not implemented")
        return self._singleton.get_instance()

    def check_implementation(self, implementation: LazySingleton):
        """
        Checks that `implement()` would succeed, without changing anything.
        Repeating the current implementation is a no-op and always passes.

        :param implementation: singleton implementing the interface
        :raises TypeError: if the implementation's class isn't a subclass of
            the interface, or another implementation is already set
        :raises SingletonFrozenError: if the binding is frozen and already implemented
        """
        with _bindings_lock:
            if not issubclass(implementation.cls, self.interface):
                raise TypeError(f"Class {implementation.cls.__name__} is not a subclass of {self.interface.__name__}")
            if implementation is self._implementation:
                return
            if self._implementation is not None:
                if self.frozen:
                    raise SingletonFrozenError(
                        f"Interface {self.interface.__name__} was already injected "
                        f"and its implementation cannot be changed"
                    )
                raise TypeError(
                    f"Interface {self.interface.__name__} is already implemented by {self._implementation.cls.__name__}; "
                    f"use @Injector.override to replace it"
                )

    def implement(self, implementation: LazySingleton):
        """
        Binds the interface to the singleton implementing it. Repeating the
        current implementation is a no-op. A frozen binding accepts its first
        implementation, since it is frozen only if it already has an override,
        which keeps winning.

        :param implementation: singleton implementing the interface
        :raises TypeError: see `check_implementation`
        :raises SingletonFrozenError: see `check_implementation`
        """
        with _bindings_lock:
            self.check_implementation(implementation)
            self._implementation = implementation

    def check_override(self, override: LazySingleton):
        """
        Checks that `override()` would succeed, without changing anything.
        See `LazySingleton.check_override`.

        :param override: singleton to inject instead of the implementation
        """
        self._singleton.check_override(override)

    def override(self, override: LazySingleton):
        """
        Makes `get_instance()` return the instance of `override` instead of the
        implementation's, whichever of them was bound first. See
        `LazySingleton.override` for the rules.

        :param override: singleton to inject instead of the implementation
        """
        self._singleton.override(override)


class InterfaceResolver:
    """
    Registry of interfaces and their `LazyInterfaceImpl` bindings.

    Not threadsafe on its own: `Injector` accesses it only while holding its
    registry lock.
    """
    def __init__(self):
        self._interfaces: dict[type, LazyInterfaceImpl] = dict()

    def resolve(self, interface: type) -> LazyInterfaceImpl:
        """
        Returns the binding of an interface.

        :param interface: registered interface
        :return: binding of the interface
        :raises TypeError: if `interface` isn't registered
        """
        if interface not in self._interfaces:
            raise TypeError(f"Interface {interface.__name__!r} is not registered")
        return self._interfaces[interface]

    def is_interface(self, interface: type) -> bool:
        """
        :param interface: class to check
        :return: whether the class is a registered interface
        """
        return interface in self._interfaces

    def interfaces(self) -> Iterator[type]:
        """
        :return: iterator over all registered interfaces
        """
        return iter(self._interfaces)

    def bindings(self) -> Iterator[LazyInterfaceImpl]:
        """
        :return: iterator over the bindings of all registered interfaces
        """
        return iter(self._interfaces.values())

    def register(self, interface: type):
        """
        Registers an interface with a fresh, unbound `LazyInterfaceImpl`.

        :param interface: abstract class to register as an interface
        :raises TypeError: if `interface` isn't abstract
        """
        self._interfaces[interface] = LazyInterfaceImpl(interface)
