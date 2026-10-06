"""
Registry of interfaces, used by `Injector`.
"""
from inspect import isabstract
from typing import Iterator

from smalldi._singleton import LazySingleton


class InterfaceResolver:
    """
    Registry of interfaces and their `LazySingleton`s.

    Every interface gets its own `LazySingleton`, which delegates to the
    singleton implementing or overriding it (see `LazySingleton.implement` and
    `LazySingleton.override`), and holds whether the interface is frozen. The
    interface class itself is abstract, so it is never instantiated.

    Not threadsafe on its own: `Injector` accesses it only while holding its
    registry lock.
    """
    def __init__(self):
        self._interfaces: dict[type, LazySingleton] = dict()

    def resolve(self, interface: type) -> LazySingleton:
        """
        Returns the `LazySingleton` of an interface.

        :param interface: registered interface
        :return: singleton of the interface
        :raises TypeError: if `interface` isn't registered
        """
        if interface not in self._interfaces:
            raise TypeError(f"Interface {interface!r} is not registered")
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

    def singletons(self) -> Iterator[LazySingleton]:
        """
        :return: iterator over the singletons of all registered interfaces
        """
        return iter(self._interfaces.values())

    def register(self, interface: type):
        """
        Registers an interface with a fresh `LazySingleton`, so registering an
        already registered interface drops its implementation and override,
        and unfreezes it.

        :param interface: abstract class to register as an interface
        :raises TypeError: if `interface` isn't abstract
        """
        if not isabstract(interface):
            raise TypeError(f"Interface {interface!r} is not abstract")
        self._interfaces[interface] = LazySingleton(interface)
