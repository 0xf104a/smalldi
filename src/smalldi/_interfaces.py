"""
Interfaces and their bindings to the singletons implementing or overriding them, used by `Injector`.
"""
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

    Every method is guarded by `@threadsafe`, which takes a reentrant lock
    stored on the instance for the duration of the call, including the
    constructor call inside `get_impl()`.

    :ivar interface: the abstract class
    :ivar _implementation: `LazySingleton` declared with `@Injector.implements`, or None
    :ivar _override: `LazySingleton` declared with `@Injector.override`, or None
    :ivar _frozen: whether an instance was requested through this binding
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
        if self._override is not None:
            raise TypeError(f"Interface {self.interface.__name__!r} is already overridden")
        if target is self._implementation:
            raise TypeError(f"Interface {self.interface.__name__!r} can't be overridden by its own implementation")
        target._mark_as_override()
        self._override = target

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
        if self._implementation is not None:
            raise RuntimeError(f"Interface {self.interface.__name__!r} is already implemented")
        if target is self._override:
            raise TypeError(f"Interface {self.interface.__name__!r} can't be implemented by its own override")
        if self._frozen and self._override is None:
            raise SingletonFrozenError(f"Interface {self.interface.__name__!r} was already frozen")
        self._implementation = target

    @threadsafe
    def get_impl(self) -> Any:
        """
        Returns the instance of the override, or of the implementation if there is no override.

        The binding is frozen first, so it stays frozen if it turns out to be
        unbound or the constructor fails.

        :return: the instance
        :raises RuntimeError: if the interface has neither an override nor an implementation
        :raises RuntimeError: from `LazySingleton.get_instance()`, on a circular dependency
        :raises Exception: any exception raised by the constructor propagates unchanged
        """
        self._frozen = True
        target = self._override if self._override is not None else self._implementation
        if target is None:
            raise RuntimeError(f"Interface {self.interface.__name__!r} is not implemented")
        return target.get_instance()

class InterfaceResolver:
    """
    Registry of interfaces and their `_LazyInterfaceImpl` bindings.

    Every method is guarded by `@threadsafe`, which takes a reentrant lock
    stored on the resolver for the duration of the call; `get_instance()`
    therefore holds it while a constructor runs. `Injector` calls the resolver
    while holding its own class mutex as well.
    """
    def __init__(self):
        """
        Creates an empty registry.
        """
        self._interfaces: dict[type, _LazyInterfaceImpl] = dict()

    @threadsafe
    def get_instance(self, interface: type) -> Any:
        """
        Returns the instance bound to an interface, creating it if needed, and freezes the binding.

        :param interface: registered interface
        :return: instance of the interface's override, or of its implementation
        :raises TypeError: if `interface` isn't registered
        :raises RuntimeError: if the interface has neither an override nor an implementation,
            or on a circular dependency
        :raises Exception: any exception raised by the constructor propagates unchanged
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
