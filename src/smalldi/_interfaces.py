"""
Interfaces and their bindings to the singletons implementing or overriding them, used by `Injector`.
"""
import copy
import threading
from inspect import isabstract
from typing import Any, Type

from smalldi._singleton import LazySingleton, SingletonFrozenError
from smalldi.concurrency import threadsafe


class _LazyInterfaceImpl:
    """
    Binding of one interface to the `LazySingleton` objects implementing and overriding it.

    The `LazySingleton` objects are the ones owned by `Injector`; the binding
    only refers to them. An override wins over an implementation. The binding
    is frozen once an instance was requested through it, even if it had no
    override or implementation at that moment; a frozen binding accepts no
    override, and an implementation only if an override is in place.

    The reentrant lock `__instance_mutex__` guards the binding. `override()`
    and `implement()` hold it for the whole call through `@threadsafe`;
    `get_impl()` holds it only to freeze the binding and pick the target, and
    asks the target for its instance after releasing it.

    :ivar interface: the abstract class
    :ivar implementation_singleton: `LazySingleton` declared with `@Injector.implements`, or None
    :ivar override_singleton: `LazySingleton` declared with `@Injector.override`, or None
    :ivar _frozen: whether an instance was requested through this binding
    :ivar __instance_mutex__: the lock guarding the binding
    """
    def __init__(self, interface: Type):
        """
        :param interface: abstract class to bind
        :raises TypeError: if `interface` isn't abstract
        """
        if not isabstract(interface):
            raise TypeError(f"Interface {interface.__name__!r} is not abstract")
        self.interface = interface
        self.implementation_singleton: LazySingleton | None = None
        self.override_singleton: LazySingleton | None = None
        self._frozen = False
        self.__instance_mutex__ = threading.RLock()

    @threadsafe
    def override(self, target: LazySingleton):
        """
        Binds the override of the interface. All checks run before anything changes.

        The target's lock is taken while it is marked as an override.

        :param target: `LazySingleton` of the overriding class
        :raises SingletonFrozenError: if the binding is frozen
        :raises TypeError: if the interface is already overridden, `target` is its implementation,
            or `target` already delegates to another singleton or has an override class
        """
        if self._frozen:
            raise SingletonFrozenError(f"Interface {self.interface.__name__!r} was already frozen")
        if self.override_singleton is not None:
            raise TypeError(f"Interface {self.interface.__name__!r} is already overridden")
        if target is self.implementation_singleton:
            raise TypeError(f"Interface {self.interface.__name__!r} can't be overridden by its own implementation")
        target._mark_as_override()
        self.override_singleton = target

    @threadsafe
    def implement(self, target: LazySingleton):
        """
        Binds the implementation of the interface. All checks run before anything changes.

        `target` isn't marked in any way: a singleton that delegates to an
        override may implement an interface, and the interface then resolves
        to the override's instance.

        :param target: `LazySingleton` of the implementing class
        :raises RuntimeError: if the interface already has an implementation
        :raises TypeError: if `target` is the interface's override
        :raises SingletonFrozenError: if the binding is frozen and has no override
        """
        if self.implementation_singleton is not None:
            raise RuntimeError(f"Interface {self.interface.__name__!r} is already implemented")
        if target is self.override_singleton:
            raise TypeError(f"Interface {self.interface.__name__!r} can't be implemented by its own override")
        if self._frozen and self.override_singleton is None:
            raise SingletonFrozenError(f"Interface {self.interface.__name__!r} was already frozen")
        self.implementation_singleton = target

    def get_impl(self) -> Any:
        """
        Returns the instance of the override, or of the implementation if there is no override.

        The binding is frozen first, so it stays frozen if it turns out to be
        unbound or the constructor fails. The binding's lock is released before
        the target is asked for its instance.

        :return: the instance
        :raises RuntimeError: if the interface has neither an override nor an implementation
        :raises RuntimeError: from `LazySingleton.get_instance()`, on a circular dependency
        :raises Exception: any exception raised by the constructor propagates unchanged
        """
        with self.__instance_mutex__:
            self._frozen = True
            target = self.override_singleton if self.override_singleton is not None else self.implementation_singleton
        if target is None:
            raise RuntimeError(f"Interface {self.interface.__name__!r} is not implemented")
        return target.get_instance()

    def stacked(self) -> 'InterfaceResolver':
        new_instance = self.__class__(self.interface)
        my_impl = None
        if self.override_singleton is not None:
            my_impl = self.override_singleton
        else:
            my_impl = self.implementation_singleton
        new_instance.implementation_singleton = my_impl
        return new_instance

class InterfaceResolver:
    """
    Registry of interfaces and their `_LazyInterfaceImpl` bindings.

    The reentrant lock `__instance_mutex__` guards the registry. Every method
    holds it for the whole call; none of them asks a singleton for its
    instance. `Injector` calls the resolver while holding its own class mutex
    as well.
    """
    def __init__(self, interfaces: dict[type, _LazyInterfaceImpl] | None = None):
        """
        Creates an empty registry.
        """
        if interfaces is None:
            interfaces = dict()
        self._interfaces: dict[type, _LazyInterfaceImpl] = interfaces
        self.__instance_mutex__ = threading.RLock()

    def get_binding(self, interface: type) -> "_LazyInterfaceImpl":
        """
        Returns the binding of a registered interface, without resolving or freezing it.

        :param interface: registered interface
        :return: the interface's `_LazyInterfaceImpl`
        :raises TypeError: if `interface` isn't registered
        """
        with self.__instance_mutex__:
            if interface not in self._interfaces:
                raise TypeError(f"Interface {interface.__name__!r} is not registered")
            return self._interfaces[interface]

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
        Registers an interface with a fresh, unbound `_LazyInterfaceImpl`.

        :param interface: abstract class to register as an interface
        :raises TypeError: if `interface` is already registered, or isn't abstract
        """
        if interface in self._interfaces:
            raise TypeError(f"Interface {interface.__name__!r} is already registered")
        if not isabstract(interface):
            raise TypeError(f"Class {interface} is not abstract and cannot be an interface. Maybe you meant to use @Injector.singleton instead?")
        self._interfaces[interface] = _LazyInterfaceImpl(interface)

    @threadsafe
    def override(self, interface: Type, new_impl: Type, target: LazySingleton):
        """
        Binds `target` as the override of `interface`.

        :param interface: registered interface
        :param new_impl: the overriding class, checked to be a subclass of `interface`
        :param target: `LazySingleton` of `new_impl`
        :raises TypeError: if `interface` isn't registered, `new_impl` isn't a subclass of it,
            the interface is already overridden, `target` is its implementation, or `target`
            already delegates to another singleton
        :raises SingletonFrozenError: if the interface's binding is frozen
        """
        if not interface in self._interfaces:
            raise TypeError(f"Interface {interface.__name__!r} is not registered")
        if not issubclass(new_impl, interface):
            raise TypeError(f"Class {new_impl} is not a subclass of {interface}")
        self._interfaces[interface].override(target)

    @threadsafe
    def implement(self, interface: Type, impl: Type, target: LazySingleton):
        """
        Binds `target` as the implementation of `interface`.

        :param interface: registered interface
        :param impl: the implementing class, checked to be a subclass of `interface`
        :param target: `LazySingleton` of `impl`
        :raises TypeError: if `interface` isn't registered, `impl` isn't a subclass of it,
            or `target` is the interface's override
        :raises RuntimeError: if the interface already has an implementation
        :raises SingletonFrozenError: if the interface's binding is frozen and has no override
        """
        if not interface in self._interfaces:
            raise TypeError(f"Interface {interface.__name__!r} is not registered")
        if not issubclass(impl, interface):
            raise TypeError(f"Class {impl} is not a subclass of {interface}")
        self._interfaces[interface].implement(target)

    @threadsafe
    def rewired(self, new_singletons: dict[type, LazySingleton]) -> 'InterfaceResolver':
        new_interfaces: dict[type, _LazyInterfaceImpl] = dict()
        for interface, target in self._interfaces.items():
            new_target = _LazyInterfaceImpl(interface)
            if target.implementation_singleton is not None:
                if target.implementation_singleton.implementation_cls is not None:
                    new_target.implementation_singleton = (new_singletons
                                                           .get(target.implementation_singleton.implementation_cls,
                                                                None))
            if target.override_singleton is not None:
                if target.override_singleton.implementation_cls is not None:
                    new_target.override_singleton = (new_singletons
                                                      .get(target.override_singleton.implementation_cls,
                                                           None))
            new_interfaces[interface] = new_target
        return InterfaceResolver(new_interfaces)

    @threadsafe
    def stacked(self) -> 'InterfaceResolver':
        new_interfaces = dict()
        for interface, target in self._interfaces.items():
            new_interfaces[interface] = target.stacked()
        return InterfaceResolver(new_interfaces)