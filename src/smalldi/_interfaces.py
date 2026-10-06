"""
Bindings of interfaces to the singletons implementing them, used by `Injector`.
"""
from inspect import isabstract
from typing import Iterator

from smalldi._singleton import LazySingleton


class InterfaceResolver:
    """
    Registry of interfaces and the singletons implementing them.

    Each registered interface has at most one implementation and at most one
    override. The override, when set, is used instead of the implementation,
    whichever of them was set first. An interface is frozen once it was
    resolved for injection, after which `Injector.override` refuses to set an
    override. Not threadsafe on its own: `Injector` accesses it only while
    holding its registry lock.
    """
    def __init__(self):
        self._interfaces: dict[type, LazySingleton | None] = dict()
        self._overrides: dict[type, LazySingleton] = dict()
        self._frozen: set[type] = set()

    def resolve(self, interface: type) -> LazySingleton:
        """
        Returns the singleton to inject for an interface: its override if one
        is set, its implementation otherwise.

        :param interface: registered interface
        :return: singleton bound to the interface
        :raises TypeError: if `interface` isn't registered
        :raises NotImplementedError: if `interface` has neither an override nor an implementation yet
        """
        if interface not in self._interfaces:
            raise TypeError(f"Interface {interface!r} is not registered")
        singleton = self._overrides.get(interface, self._interfaces[interface])
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
        Returns the singleton implementing an interface, ignoring any override,
        without failing when there is none.

        :param interface: registered interface
        :return: singleton bound to the interface, or None if it isn't implemented yet
        :raises TypeError: if `interface` isn't registered
        """
        if interface not in self._interfaces:
            raise TypeError(f"Interface {interface!r} is not registered")
        return self._interfaces[interface]

    def override_of(self, interface: type) -> LazySingleton | None:
        """
        Returns the singleton overriding an interface, without failing when
        there is none.

        :param interface: registered interface
        :return: singleton overriding the interface, or None if it isn't overridden
        :raises TypeError: if `interface` isn't registered
        """
        if interface not in self._interfaces:
            raise TypeError(f"Interface {interface!r} is not registered")
        return self._overrides.get(interface)

    def is_bound(self, interface: type) -> bool:
        """
        :param interface: class to check
        :return: whether the interface is registered and has an override or an implementation
        """
        return self._interfaces.get(interface) is not None or interface in self._overrides

    def register(self, interface: type):
        """
        Registers an interface without an implementation or override.
        Registering an already registered interface drops its implementation
        and override, and unfreezes it.

        :param interface: abstract class to register as an interface
        :raises TypeError: if `interface` isn't abstract
        """
        if not isabstract(interface):
            raise TypeError(f"Interface {interface!r} is not abstract")
        self._interfaces[interface] = None
        self._overrides.pop(interface, None)
        self._frozen.discard(interface)

    def freeze(self, interface: type):
        """
        Marks an interface as frozen, so `Injector.override` may no longer set
        its override.

        :param interface: registered interface
        :raises TypeError: if `interface` isn't registered
        """
        if interface not in self._interfaces:
            raise TypeError(f"Interface {interface!r} is not registered")
        self._frozen.add(interface)

    def is_frozen(self, interface: type) -> bool:
        """
        :param interface: class to check
        :return: whether the interface is registered and frozen
        """
        return interface in self._frozen

    def set_implementation(self, interface: type, implementation: LazySingleton):
        """
        Binds an interface to the singleton implementing it, replacing the
        previous implementation. An override, if set, still takes precedence.
        Doesn't check for conflicts or freezing: that's up to the caller.

        :param interface: registered interface
        :param implementation: singleton implementing the interface
        :raises TypeError: if `interface` isn't registered
        """
        if interface not in self._interfaces:
            raise TypeError(f"Interface {interface!r} is not registered")
        self._interfaces[interface] = implementation

    def set_override(self, interface: type, override: LazySingleton):
        """
        Sets the singleton to inject for an interface instead of its
        implementation, replacing the previous override. Doesn't check for
        conflicts or freezing: that's up to the caller.

        :param interface: registered interface
        :param override: singleton overriding the interface
        :raises TypeError: if `interface` isn't registered
        """
        if interface not in self._interfaces:
            raise TypeError(f"Interface {interface!r} is not registered")
        self._overrides[interface] = override

    def override_implementation(self, interface: type, implementation: type):
        """
        Overrides the class instantiated by the singleton resolved for an
        interface (its override if set, its implementation otherwise).
        See `LazySingleton.override` for the rules.

        :param interface: registered interface
        :param implementation: subclass of the current implementation class
        :raises TypeError: if `interface` isn't registered
        :raises NotImplementedError: if no singleton implements `interface` yet
        """
        self.resolve(interface).override(implementation)
