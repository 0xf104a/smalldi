"""
Interfaces and their bindings to the singletons implementing or overriding them, used by `Injector`.
"""
import threading
from inspect import isabstract
from typing import Any, Callable, Type

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

    The reentrant lock `__instance_mutex__` guards the binding. `override()`,
    `implement()` and `resolve()` hold it for the whole call through
    `@threadsafe`; `get_impl()` holds it only through `resolve()`, and asks
    the target for its instance after releasing it. `Injector` calls
    `resolve()` under its class mutex while it looks the interface up.

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
    def override(self, new_impl: Type, target: LazySingleton):
        """
        Binds the override of the interface. All checks run before anything changes.

        The target's lock is taken while it is marked as an override on behalf
        of `new_impl`.

        :param new_impl: the overriding class
        :param target: `LazySingleton` registered for `new_impl`
        :raises SingletonFrozenError: if the binding is frozen
        :raises TypeError: if the interface is already overridden, `target` is its implementation,
            or `new_impl` is overridden by another singleton
        """
        if self._frozen:
            raise SingletonFrozenError(f"Interface {self.interface.__name__!r} was already frozen")
        if self.override_singleton is not None:
            raise TypeError(f"Interface {self.interface.__name__!r} is already overridden")
        if target is self.implementation_singleton:
            raise TypeError(f"Interface {self.interface.__name__!r} can't be overridden by its own implementation")
        target._mark_as_override(new_impl)
        self.override_singleton = target

    @threadsafe
    def implement(self, target: LazySingleton):
        """
        Binds the implementation of the interface. All checks run before anything changes.

        `target` isn't marked in any way: an overridden singleton may implement
        an interface, and the interface then resolves to the override's
        instance, which the shared `LazySingleton` creates.

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

    @threadsafe
    def rebind(self, old: LazySingleton, new: LazySingleton) -> None:
        """
        Replaces `old` by `new` wherever this binding refers to it.

        Called when `Injector` replaces the `LazySingleton` of a class by the
        one it shares with the singleton it overrides, so the binding keeps
        referring to the object `Injector` owns.

        :param old: `LazySingleton` being discarded
        :param new: `LazySingleton` registered in its place
        """
        if self.implementation_singleton is old:
            self.implementation_singleton = new
        if self.override_singleton is old:
            self.override_singleton = new

    @threadsafe
    def resolve(self) -> LazySingleton:
        """
        Freezes the binding and its target, and returns the target, without requesting an instance.

        The target is the override, or the implementation if there is no
        override. The binding is frozen first, so it stays frozen if it turns
        out to be unbound.

        :return: the `LazySingleton` to ask for the instance
        :raises RuntimeError: if the interface has neither an override nor an implementation
        """
        self._frozen = True
        target = self.override_singleton if self.override_singleton is not None else self.implementation_singleton
        if target is None:
            raise RuntimeError(f"Interface {self.interface.__name__!r} is not implemented")
        target._freeze()
        return target

    def get_impl(self) -> Any:
        """
        Returns the instance of the override, or of the implementation if there is no override.

        The binding and its target are frozen first by `resolve()`, so they
        stay frozen if the binding turns out to be unbound or the constructor
        fails. The binding's lock is released before the target is asked for
        its instance.

        :return: the instance
        :raises RuntimeError: if the interface has neither an override nor an implementation
        :raises RuntimeError: from `LazySingleton.get_instance()`, on a circular dependency
        :raises Exception: any exception raised by the constructor propagates unchanged
        """
        return self.resolve().get_instance()

    @threadsafe
    def _freeze(self) -> None:
        """
        Freezes the binding without resolving it.

        `InterfaceResolver.redeclare` calls it on a binding built for a declared
        context whose implementation is a preset instance, so the binding
        refuses an override like one an instance was requested through.
        """
        self._frozen = True

    def stacked(self) -> '_LazyInterfaceImpl':
        """
        Returns a new, unfrozen binding whose implementation is this binding's override, or its implementation if it
        has no override, and which has no override.

        :return: the new binding, referring to the same `LazySingleton` object
        """
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
            the interface is already overridden, `target` is its implementation, or `new_impl`
            is overridden by another singleton
        :raises SingletonFrozenError: if the interface's binding is frozen
        """
        if not interface in self._interfaces:
            raise TypeError(f"Interface {interface.__name__!r} is not registered")
        if not issubclass(new_impl, interface):
            raise TypeError(f"Class {new_impl} is not a subclass of {interface}")
        self._interfaces[interface].override(new_impl, target)

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
    def rebind(self, old: LazySingleton, new: LazySingleton) -> None:
        """
        Replaces `old` by `new` in every binding that refers to it.

        :param old: `LazySingleton` being discarded by `Injector`
        :param new: `LazySingleton` registered in its place
        """
        for binding in self._interfaces.values():
            binding.rebind(old, new)

    @threadsafe
    def rewired(self, derived: dict[int, LazySingleton],
                derive: Callable[[LazySingleton], LazySingleton]) -> 'InterfaceResolver':
        """
        Returns a new resolver with a new, unfrozen binding per interface, referring to the derived singletons.

        Each binding's implementation and override are looked up in `derived`
        by the `id` of the `LazySingleton` they refer to here, so a binding
        follows the object the context being derived holds for its singleton.
        A target absent from `derived`, a binding-only singleton holding the
        preset of an `ImplementationOf[I]` field, is passed to `derive`, the
        transform the derivation applies to its registry singletons, and the
        result is stored in `derived`; so targets that are one object here are
        one object in the new resolver, and `derived` is extended with the
        objects made for such targets.

        :param derived: `id` of each singleton of the source context mapped to the object the derived context holds
            for it; extended with the objects made for targets absent from it
        :param derive: makes the derived context's object for a singleton absent from `derived`
        :return: the new resolver
        """
        def rewire(target: LazySingleton | None) -> LazySingleton | None:
            if target is None:
                return None
            new_target = derived.get(id(target))
            if new_target is None:
                new_target = derive(target)
                derived[id(target)] = new_target
            return new_target

        new_interfaces: dict[type, _LazyInterfaceImpl] = dict()
        for interface, binding in self._interfaces.items():
            new_binding = _LazyInterfaceImpl(interface)
            new_binding.implementation_singleton = rewire(binding.implementation_singleton)
            new_binding.override_singleton = rewire(binding.override_singleton)
            new_interfaces[interface] = new_binding
        return InterfaceResolver(new_interfaces)

    @threadsafe
    def redeclare(self, interface: type, implementation: LazySingleton | None = None) -> None:
        """
        Gives `interface` a fresh binding, replacing any, and registers `interface` if it isn't registered.

        Called by `smalldi.context._DeclaredContext.derive` on the resolver of a
        child context that no slice sees yet, once per `ImplementationOf[I]`
        field, after `rewired()`. Without `implementation` the binding has
        neither implementation nor override, so the block binds it with
        `@Injector.implements` or `@Injector.override`. With `implementation`,
        a binding-only `LazySingleton` which already holds the preset instance
        and is referenced by nothing but this binding, the binding gets it as
        its implementation and is frozen. The caller checks the preset against
        `interface`. The binding is built completely before it is stored.

        :param interface: abstract class to bind
        :param implementation: the binding-only `LazySingleton` holding the preset, or None for an unbound binding
        :raises TypeError: if `interface` isn't abstract
        """
        binding = _LazyInterfaceImpl(interface)
        if implementation is not None:
            binding.implement(implementation)
            binding._freeze()
        self._interfaces[interface] = binding

    @threadsafe
    def stacked(self) -> 'InterfaceResolver':
        """
        Returns a new resolver in which every binding's override, or its implementation if it has none, is the
        implementation of a new, unfrozen binding without an override.

        Called on the resolver `rewired()` built for a `STACK` child, whose
        bindings already refer to the fresh singletons of that child.

        :return: the new resolver
        """
        new_interfaces: dict[type, _LazyInterfaceImpl] = dict()
        for interface, target in self._interfaces.items():
            new_interfaces[interface] = target.stacked()
        return InterfaceResolver(new_interfaces)