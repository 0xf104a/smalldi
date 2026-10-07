"""
Interfaces and the singletons implementing them, used by `Injector`.
"""
from inspect import isabstract
from typing import Any, Type

from smalldi._singleton import LazySingleton
from smalldi.concurrency import threadsafe


class _LazyInterfaceImpl:
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

    @threadsafe
    def override(self, override_cls: Type):
        if not issubclass(override_cls, self.interface):
            raise TypeError(f"{override_cls!r} is not a subclass of {self.interface!r}")
        if self._implementation is None:
            self._implementation = LazySingleton(None, override_cls)
        elif self._implementation.override_cls is not None:
            raise TypeError(f"Interface {self.interface.__name__!r} is already overridden")
        else:
            self._implementation.override(override_cls)

    @threadsafe
    def implement(self, implementation_cls: Type):
        if self._implementation is not None:
            if self._implementation.implementation_cls is not None:
                raise RuntimeError(f"Interface {self.interface.__name__!r} is already implemented")
            self._implementation.set_base(implementation_cls)
        else:
            self._implementation = LazySingleton(implementation_cls, None)

    @threadsafe
    def get_impl(self) -> Any:
        if self._implementation is None:
            raise RuntimeError(f"Interface {self.interface.__name__!r} is not implemented")
        return self._implementation.get_instance()

class InterfaceResolver:
    """
    Registry of interfaces and their `LazyInterfaceImpl` bindings.

    Not threadsafe on its own: `Injector` accesses it only while holding its
    registry lock.
    """
    def __init__(self):
        self._interfaces: dict[type, _LazyInterfaceImpl] = dict()

    @threadsafe
    def get_instance(self, interface: type) -> Any:
        """
        Returns the binding of an interface.

        :param interface: registered interface
        :return: binding of the interface
        :raises TypeError: if `interface` isn't registered
        """
        if interface not in self._interfaces:
            raise TypeError(f"Interface {interface.__name__!r} is not registered")
        return self._interfaces[interface].get_impl()

    @threadsafe
    def is_interface(self, interface: type) -> bool:
        """
        :param interface: class to check
        :return: whether the class is a registered interface
        """
        return interface in self._interfaces

    @threadsafe
    def register(self, interface: type):
        """
        Registers an interface with a fresh, unbound `LazyInterfaceImpl`.

        :param interface: abstract class to register as an interface
        :raises TypeError: if `interface` isn't abstract
        """
        if interface in self._interfaces:
            raise TypeError(f"Interface {interface.__name__!r} is already registered")
        if not isabstract(interface):
            raise TypeError(f"Class {interface} is not abstract and cannot be an interface. Maybe you meant to use @Injector.singleton instead?")
        self._interfaces[interface] = _LazyInterfaceImpl(interface)

    @threadsafe
    def override(self, interface: Type, new_impl: Type):
        if not interface in self._interfaces:
            raise TypeError(f"Interface {interface.__name__!r} is not registered")
        if not issubclass(new_impl, interface):
            raise TypeError(f"Class {new_impl} is not a subclass of {interface}")
        self._interfaces[interface].override(new_impl)

    @threadsafe
    def implement(self, interface: Type, impl: Type):
        if not interface in self._interfaces:
            raise TypeError(f"Interface {interface.__name__!r} is not registered")
        if not issubclass(impl, interface):
            raise TypeError(f"Class {impl} is not a subclass of {interface}")
        self._interfaces[interface].implement(impl)
