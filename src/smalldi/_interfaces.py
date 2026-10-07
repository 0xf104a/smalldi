"""
Interfaces and the singletons implementing them, used by `Injector`.
"""
from inspect import isabstract
from typing import Any, Type

from smalldi._singleton import LazySingleton, SingletonFrozenError
from smalldi.concurrency import threadsafe


class _LazyInterfaceImpl:
    """
    Binding of an interface to the registry-owned `LazySingleton`s implementing and overriding it.

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
        self._override: LazySingleton | None = None
        self._frozen = False

    @threadsafe
    def override(self, target: LazySingleton):
        if self._frozen:
            raise SingletonFrozenError(f"Interface {self.interface.__name__!r} was already frozen")
        if self._override is not None:
            raise TypeError(f"Interface {self.interface.__name__!r} is already overridden")
        if target is self._implementation:
            raise TypeError(f"Interface {self.interface.__name__!r} can't be overridden by its own implementation")
        target._mark_as_override()
        self._override = target

    @threadsafe
    def implement(self, target: LazySingleton):
        if self._implementation is not None:
            raise RuntimeError(f"Interface {self.interface.__name__!r} is already implemented")
        if target is self._override:
            raise TypeError(f"Interface {self.interface.__name__!r} can't be implemented by its own override")
        if self._frozen and self._override is None:
            raise SingletonFrozenError(f"Interface {self.interface.__name__!r} was already frozen")
        self._implementation = target

    @threadsafe
    def get_impl(self) -> Any:
        self._frozen = True
        target = self._override if self._override is not None else self._implementation
        if target is None:
            raise RuntimeError(f"Interface {self.interface.__name__!r} is not implemented")
        return target.get_instance()

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
    def override(self, interface: Type, new_impl: Type, target: LazySingleton):
        if not interface in self._interfaces:
            raise TypeError(f"Interface {interface.__name__!r} is not registered")
        if not issubclass(new_impl, interface):
            raise TypeError(f"Class {new_impl} is not a subclass of {interface}")
        self._interfaces[interface].override(target)

    @threadsafe
    def implement(self, interface: Type, impl: Type, target: LazySingleton):
        if not interface in self._interfaces:
            raise TypeError(f"Interface {interface.__name__!r} is not registered")
        if not issubclass(impl, interface):
            raise TypeError(f"Class {impl} is not a subclass of {interface}")
        self._interfaces[interface].implement(target)
