"""
Bindings of interfaces to the singletons implementing them, used by `Injector`.
"""
from typing import Iterator

from smalldi._singleton import LazySingleton


class InterfaceResolver:
    """
    Registry of interfaces and the singletons implementing them.

    Each registered interface is bound to at most one implementation. Not
    threadsafe on its own: `Injector` accesses it only while holding its
    registry lock.
    """
    def __init__(self):
        self._interfaces: dict[type, LazySingleton | None] = dict()

    def resolve(self, interface: type) -> LazySingleton:
        """
        Returns the singleton implementing an interface.

        :param interface: registered interface
        :return: singleton bound to the interface
        :raises TypeError: if `interface` isn't registered
        :raises NotImplementedError: if no singleton implements `interface` yet
        """
        if interface not in self._interfaces:
            raise TypeError(f"Interface {interface!r} is not registered")
        singleton = self._interfaces[interface]
        if singleton is None:
            raise NotImplementedError(f"Interface {interface!r} is not implemented")
        return singleton

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

    def implementation_of(self, interface: type) -> LazySingleton | None:
        """
        Returns the singleton implementing an interface, without failing when
        there is none.

        :param interface: registered interface
        :return: singleton bound to the interface, or None if it isn't implemented yet
        :raises TypeError: if `interface` isn't registered
        """
        if interface not in self._interfaces:
            raise TypeError(f"Interface {interface!r} is not registered")
        return self._interfaces[interface]

    def register(self, interface: type):
        """
        Registers an interface without an implementation.
        Registering an already registered interface drops its implementation.

        :param interface: class to register as an interface
        """
        self._interfaces[interface] = None

    def set_implementation(self, interface: type, implementation: LazySingleton):
        """
        Binds an interface to the singleton implementing it, replacing the
        previous binding.

        :param interface: registered interface
        :param implementation: singleton implementing the interface
        :raises TypeError: if `interface` isn't registered
        """
        if interface not in self._interfaces:
            raise TypeError(f"Interface {interface!r} is not registered")
        self._interfaces[interface] = implementation

    def override_implementation(self, interface: type, implementation: type):
        """
        Overrides the class instantiated by the singleton implementing an
        interface. See `LazySingleton.override` for the rules.

        :param interface: registered interface
        :param implementation: subclass of the current implementation class
        :raises TypeError: if `interface` isn't registered
        :raises NotImplementedError: if no singleton implements `interface` yet
        """
        self.resolve(interface).override(implementation)
