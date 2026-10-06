import functools
import threading
import warnings
from inspect import isabstract
from types import MappingProxyType
from typing import Any, Mapping

from smalldi._interfaces import InterfaceResolver
from smalldi._singleton import LazySingleton, SingletonFrozenError
from smalldi.concurrency import threadsafe
from smalldi.wrappers import staticclass
from smalldi.annotation import _Provide, Provide

__author__ = "Anna-Sofia Kasierocka"
__email__ = "f104a@f104a.io"
__version__ = "0.3.0"
__all__ = ["Injector", "Provide", "SingletonFrozenError"]

def _same_class(a: type, b: type) -> bool:
    """
    Whether two classes are the same class, or a reloaded version of it.

    :param a: first class
    :param b: second class
    :return: True if the classes are identical or share module and qualified name
    """
    return a is b or (a.__module__, a.__qualname__) == (b.__module__, b.__qualname__)


class _InjectorMeta(type):
    """
    Metaclass of `Injector`.
    Exists only to provide class-level read-only properties, since
    `Injector` is a static class and is never instantiated.
    """
    @property
    def singletons(cls) -> Mapping[type, Any]:
        """
        Read-only snapshot of all registered singletons and their instances.

        Reading this property instantiates every singleton that wasn't created
        yet, which freezes the whole registry: none of the singletons, nor the
        interfaces implemented so far, can be overridden afterwards. Avoid
        reading it before all overrides are done.

        The snapshot doesn't follow later changes: singletons registered after
        reading it are not included. Read the property again to see them.
        Instantiation happens outside the registry lock, so singleton
        constructors may register or inject other singletons.

        :return: read-only mapping of singleton class to its instance
        """
        with cls._registry_lock:
            registered = list(cls._singletons_available.items())
            resolver = cls._interface_resolver
            for interface in list(resolver.interfaces()):
                if resolver.is_bound(interface):
                    resolver.freeze(interface)
        return MappingProxyType({tp: s.get_instance() for tp, s in registered})

    @property
    def singletons_available(cls) -> Mapping[type, Any]:
        """
        Deprecated alias of `Injector.singletons`.

        Unlike in older versions, the returned mapping is a read-only snapshot,
        so singletons can no longer be registered or removed through it.
        Reading it freezes all singletons, like `Injector.singletons` does.

        :return: read-only mapping of singleton class to its instance
        """
        warnings.warn(
            "Injector.singletons_available is deprecated, use Injector.singletons",
            DeprecationWarning,
            stacklevel=2,
        )
        return cls.singletons


@staticclass
class Injector(metaclass=_InjectorMeta):
    """
    The injector class handles all the dependency injections.

    `Injector` is a static class: it can't be instantiated and all of its state
    is kept at class level. Classes are registered with `@Injector.singleton`
    and injected into functions with `@Injector.inject`. Registered instances
    can be inspected through the read-only `Injector.singletons` property.

    Classes marked with `@Injector.interface` may be injected too: a singleton
    declares that it implements them with `@Injector.implements`, and
    `Provide[Interface]` then receives that singleton's instance.

    Registration and lookups are guarded by a reentrant lock, so the injector
    may be used from several threads. Singletons are instantiated lazily, at
    most once each.
    """
    # Not threadsafe on their own: access only while holding _registry_lock
    _singletons_available: dict[type, LazySingleton] = dict()
    _interface_resolver = InterfaceResolver()
    _registry_lock = threading.RLock()

    @classmethod
    def _get_instance(cls, tp: type) -> Any:
        """
        Returns the instance of a registered singleton, or of the singleton
        implementing a registered interface, creating it if needed.
        Creating the instance freezes the singleton, and resolving an interface
        freezes the interface, so it can no longer be rebound by
        `Injector.override`.

        :param tp: registered singleton class or interface
        :return: the singleton instance
        :raises TypeError: if `tp` is neither a registered singleton nor an interface
        :raises NotImplementedError: if `tp` is an interface no singleton implements yet
        """
        with cls._registry_lock:
            singleton = cls._singletons_available.get(tp)
            if singleton is None and cls._interface_resolver.is_interface(tp):
                singleton = cls._interface_resolver.resolve(tp)
                cls._interface_resolver.freeze(tp)
        if singleton is None:
            raise TypeError(f"Singleton {tp} is not available")
        # Outside the lock: a constructor must not block the whole registry
        return singleton.get_instance()

    @classmethod
    def inject(cls, fn):
        """
        Injects dependencies into function.

        Every parameter annotated with `Provide[T]` receives the instance of
        singleton `T` when the function is called, unless the caller passes that
        argument explicitly by keyword. If `T` is an interface, the instance of
        the singleton implementing it is passed. Singletons are resolved on each
        call, not at decoration time, so decorating a function doesn't
        instantiate them, and overrides made before the first call are respected.

        All singletons and interfaces must already be registered when the
        function is decorated. An interface doesn't need an implementation yet:
        it must have one by the time the function is called, otherwise the call
        raises `NotImplementedError`. Dependencies passed positionally aren't
        detected: pass them by keyword to override injection.

        :param fn: function to inject dependencies into
        :return: function with injected dependencies
        :raises TypeError: if a `Provide[T]` dependency is neither a registered
            singleton nor an interface
        """
        name2type = dict()
        for name, tp in _Provide.iter_annotations(fn):
            with cls._registry_lock:
                if tp not in cls._singletons_available and not cls._interface_resolver.is_interface(tp):
                    raise TypeError(f"Singleton {tp} is not available")
            name2type[name] = tp

        @functools.wraps(fn)
        def wrapped_fn(*args, **kwargs):
            for name, tp in name2type.items():
                if name not in kwargs:
                    kwargs[name] = cls._get_instance(tp)
            return fn(*args, **kwargs)
        return wrapped_fn

    @classmethod
    def singleton(cls, target_cls):
        """
        Marks class as singleton.

        Singleton classes are instantiated only once by the injector. Their
        __init__ function should have no arguments or be annotated with
        @Injector.inject, so the injector could construct them itself.

        The class isn't instantiated here: the instance is created lazily, the
        first time it is injected or `Injector.singletons` is read. From then on
        the singleton is frozen and can't be overridden.

        Registering the same class, or a class with the same module and
        qualified name (as happens after `importlib.reload`), more than once
        emits a `RuntimeWarning` and replaces the registration. Instances which
        were already injected aren't replaced, so several instances may coexist.

        :param target_cls: Class which to be marked as injectable singleton
        :return: `target_cls` unchanged, so this may be used as a decorator
        :raises TypeError: if `target_cls` is abstract or is an interface
        """
        if isabstract(target_cls):
            raise TypeError(f"Class {target_cls} is abstract and cannot be a singleton")
        with cls._registry_lock:
            if cls._interface_resolver.is_interface(target_cls):
                raise TypeError(f"Class {target_cls} is an interface and cannot be a singleton")
            if any(_same_class(tp, target_cls) for tp in cls._singletons_available):
                warnings.warn(
                    f"Class {target_cls} is registered as a singleton more than once "
                    f"(module reload?). Already injected instances are not replaced, "
                    f"so several instances may coexist.",
                    RuntimeWarning,
                    stacklevel=2,
                )
            cls._singletons_available[target_cls] = LazySingleton(target_cls, None)
        return target_cls

    @classmethod
    def interface(cls, target_cls):
        """
        Marks class as an interface.

        Interfaces may be injected with `Provide[Interface]` once a singleton
        declares that it implements them with `@Injector.implements` or
        overrides them with `@Injector.override`. An interface must be an
        abstract class, so it can't be a singleton itself.

        Registering the same interface, or a class with the same module and
        qualified name (as happens after `importlib.reload`), more than once
        emits a `RuntimeWarning`. Registering the same class again drops its
        implementation and override.

        :param target_cls: abstract class which to be marked as an interface
        :return: `target_cls` unchanged, so this may be used as a decorator
        :raises TypeError: if `target_cls` isn't abstract or is a registered singleton
        """
        if not isabstract(target_cls):
            raise TypeError(f"Class {target_cls} is not abstract and cannot be an interface")
        with cls._registry_lock:
            if target_cls in cls._singletons_available:
                raise TypeError(f"Class {target_cls} is a singleton and cannot be an interface")
            if any(_same_class(tp, target_cls) for tp in cls._interface_resolver.interfaces()):
                warnings.warn(
                    f"Class {target_cls} is registered as an interface more than once "
                    f"(module reload?). Its implementation and override must be declared again.",
                    RuntimeWarning,
                    stacklevel=2,
                )
            cls._interface_resolver.register(target_cls)
        return target_cls

    @classmethod
    def implements(cls, *interfaces):
        """
        Declares that a singleton implements interfaces.

        Returns a decorator to apply above `@Injector.singleton`::

            @Injector.implements(Storage, Cache)
            @Injector.singleton
            class RedisStorage(Storage, Cache):
                ...

        `Provide[Storage]` and `Provide[Cache]` then receive the same instance as
        `Provide[RedisStorage]`, unless the interface is overridden with
        `@Injector.override`: the override wins regardless of which of them was
        declared first. Every interface must be registered with
        `@Injector.interface` and be a base class of the singleton. Each
        interface has at most one implementation; declaring it again for the
        same class (or a reloaded version of it) rebinds it. Either all
        interfaces are bound or, on error, none of them.

        :param interfaces: interfaces implemented by the singleton
        :return: decorator binding the interfaces and returning the class unchanged
        :raises TypeError: if no interfaces are given; the decorator raises it if
            the class isn't a registered singleton, an interface isn't registered
            or isn't a base class of the singleton, or an interface is already
            implemented by another class (use `@Injector.override` to replace it)
        """
        if not interfaces:
            raise TypeError("@Injector.implements requires at least one interface")

        def decorator(target_cls):
            with cls._registry_lock:
                singleton = cls._check_binding("implements", target_cls, interfaces)
                for interface in interfaces:
                    current = cls._interface_resolver.implementation_of(interface)
                    if current is not None and not _same_class(current.cls, target_cls):
                        raise TypeError(
                            f"Interface {interface} is already implemented by {current.cls}; "
                            f"use @Injector.override to replace it"
                        )
                for interface in interfaces:
                    cls._interface_resolver.set_implementation(interface, singleton)
            return target_cls

        return decorator

    @classmethod
    def override(cls, *interfaces):
        """
        Overrides the implementation of interfaces with another singleton.

        Returns a decorator to apply above `@Injector.singleton`::

            @Injector.override(Storage)
            @Injector.singleton
            class FakeStorage(Storage):
                ...

        `Provide[Storage]` then receives the `FakeStorage` instance instead of
        the implementation declared with `@Injector.implements`. The override
        may be declared before or after the implementation: it wins either way,
        so modules may be imported in any order. The implementation stays
        registered as a singleton, so `Provide[Implementation]` still receives it.

        Each interface may have only one override, so it is unambiguous which
        singleton gets injected; declaring it again for the same class (or a
        reloaded version of it) rebinds it. An interface is frozen once it was
        injected or `Injector.singletons` was read, after which it can't be
        overridden: declare overrides before the first injection. Every
        interface must be registered with `@Injector.interface` and be a base
        class of the singleton. Either all interfaces are overridden or, on
        error, none of them.

        :param interfaces: interfaces to override with the singleton
        :return: decorator overriding the interfaces and returning the class unchanged
        :raises TypeError: if no interfaces are given; the decorator raises it if
            the class isn't a registered singleton, an interface isn't registered
            or isn't a base class of the singleton, or an interface is already
            overridden by another class
        :raises SingletonFrozenError: raised by the decorator if an interface
            was already injected
        """
        if not interfaces:
            raise TypeError("@Injector.override requires at least one interface")

        def decorator(target_cls):
            with cls._registry_lock:
                singleton = cls._check_binding("override", target_cls, interfaces)
                for interface in interfaces:
                    current = cls._interface_resolver.override_of(interface)
                    if current is not None:
                        if not _same_class(current.cls, target_cls):
                            raise TypeError(
                                f"Interface {interface} is already overridden by {current.cls}"
                            )
                    elif cls._interface_resolver.is_frozen(interface):
                        raise SingletonFrozenError(
                            f"Interface {interface} was already injected and cannot be overridden"
                        )
                for interface in interfaces:
                    cls._interface_resolver.set_override(interface, singleton)
            return target_cls

        return decorator

    @classmethod
    def _check_binding(cls, decorator: str, target_cls: type, interfaces: tuple[type, ...]) -> LazySingleton:
        """
        Checks that a singleton may be bound to interfaces.
        Must be called while holding `_registry_lock`.

        :param decorator: name of the calling decorator, used in error messages
        :param target_cls: class to bind
        :param interfaces: interfaces to bind the class to
        :return: the singleton registered for `target_cls`
        :raises TypeError: if `target_cls` isn't a registered singleton, or an
            interface isn't registered or isn't a base class of `target_cls`
        """
        singleton = cls._singletons_available.get(target_cls)
        if singleton is None:
            raise TypeError(
                f"Class {target_cls} is not a singleton; "
                f"apply @Injector.{decorator} above @Injector.singleton"
            )
        for interface in interfaces:
            if not cls._interface_resolver.is_interface(interface):
                raise TypeError(f"Class {interface} is not an interface")
            if not issubclass(target_cls, interface):
                raise TypeError(f"Class {target_cls} is not a subclass of {interface}")
        return singleton
