import functools
import threading
from inspect import isabstract
from typing import Any

from smalldi._interfaces import InterfaceResolver
from smalldi._singleton import LazySingleton, SingletonFrozenError
from smalldi.annotation import _Provide, Provide
from smalldi.concurrency import threadsafe, mutex
from smalldi.decorator import staticclass

__author__ = "Anna-Sofia Kasierocka"
__email__ = "f104a@f104a.io"
__version__ = "0.3.0"
__all__ = ["Injector", "Provide", "SingletonFrozenError"]

@staticclass
class Injector:
    """
    The injector class handles all the dependency injections.

    `Injector` is a static class: it can't be instantiated and all of its state
    is kept at class level. Classes are registered with `@Injector.singleton`
    and injected into functions with `@Injector.inject`. Instances are
    reached through injection only; the deprecated `Injector.singletons_available`
    still exposes a read-only snapshot of them, with a warning.

    Classes marked with `@Injector.interface` may be injected too: a singleton
    declares that it implements them with `@Injector.implements`, and
    `Provide[Interface]` then receives that singleton's instance. Both
    interfaces and singletons may be replaced with `@Injector.override`.

    Every registered singleton is held by a `LazySingleton` and every
    interface by a `LazyInterfaceImpl`. They know what they delegate to (an
    override, an implementation) and whether they are frozen; the injector
    only looks them up and binds them.

    Registration, lookups and bindings are guarded by one reentrant lock,
    never held while an instance is being created, so the injector may be
    used from several threads and constructors may use the injector.
    Singletons are instantiated lazily, at most once each.
    """
    # Not threadsafe on their own: access only while holding _registry_lock.
    # This is the same lock that guards the bindings of every LazySingleton and
    # LazyInterfaceImpl, so looking a singleton up and binding it is one step.
    # It is reentrant and never held while an instance is being created.
    _singletons_available: dict[type, LazySingleton] = dict()
    _interface_resolver = InterfaceResolver()
    __class_mutex__ = threading.RLock()

    @threadsafe
    @classmethod
    def get_instance(cls, tp: type) -> Any:
        """
        Returns the instance to inject for a registered singleton or interface,
        following overrides and implementations, creating it if needed.
        Freezes every singleton on the way, so none of them can be overridden
        afterwards.

        :param tp: registered singleton class or interface
        :return: the singleton instance
        :raises TypeError: if `tp` is neither a registered singleton nor an interface
        :raises NotImplementedError: if `tp` is an interface without an implementation or override
        """
        if cls._interface_resolver.is_interface(tp):
            return cls._interface_resolver.get_instance(tp)
        singleton = cls._singletons_available[tp]
        return singleton.get_instance()

    @classmethod
    def inject(cls, fn):
        """
        Injects dependencies into function.

        Every parameter annotated with `Provide[T]` receives the instance of
        singleton `T` when the function is called, unless the caller passes that
        argument explicitly by keyword. If `T` is an interface, the instance of
        the singleton implementing it is passed. If `T` is overridden with
        `@Injector.override`, the override's instance is passed. Singletons are resolved on each
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
            with cls.__class_mutex__:
                if tp not in cls._singletons_available and not cls._interface_resolver.is_interface(tp):
                    raise TypeError(f"Singleton {tp} is not available")
            name2type[name] = tp

        @functools.wraps(fn)
        def wrapped_fn(*args, **kwargs):
            for argname, _tp in name2type.items():
                if argname not in kwargs:
                    kwargs[argname] = cls.get_instance(_tp)
            return fn(*args, **kwargs)
        return wrapped_fn

    @threadsafe
    @classmethod
    def singleton(cls, target_cls):
        if isabstract(target_cls):
            raise TypeError(f"Class {target_cls} is abstract and cannot be a singleton. Maybe you meant to use @Injector.interface instead?")
        if target_cls in cls._singletons_available:
            raise TypeError(f"Class {target_cls} is already a singleton")
        cls._singletons_available[target_cls] = LazySingleton(target_cls)
        return target_cls

    @threadsafe
    @classmethod
    def _override_singleton(cls, source_cls):
        @mutex(cls.__class_mutex__)
        def wrapper(new_cls):
            if source_cls not in cls._singletons_available:
                raise TypeError(f"Class {source_cls} is not a known singleton. You must override an existing singleton.")
            if not issubclass(new_cls, source_cls):
                raise TypeError(f"{new_cls!r} is not a subclass of {source_cls!r}")
            singleton = cls._singletons_available[source_cls]
            singleton.override(new_cls)
            cls._singletons_available[new_cls] = singleton
            return new_cls
        return wrapper

    @threadsafe
    @classmethod
    def _override_interface(cls, interface):
        @mutex(cls.__class_mutex__)
        def wrapper(new_impl):
            cls._interface_resolver.override(interface, new_impl)
            return new_impl
        return wrapper

    @threadsafe
    @classmethod
    def interface(cls, target_cls):
        if not isabstract(target_cls):
            raise TypeError(f"Class {target_cls} is not abstract and cannot be an interface. Maybe you meant to use @Injector.singleton instead?")
        cls._interface_resolver.register(target_cls)
        return target_cls

    @threadsafe
    @classmethod
    def override(cls, what: type):
        if cls._interface_resolver.is_interface(what):
            return cls._override_interface(what)
        else:
            return cls._override_singleton(what)

    @threadsafe
    @classmethod
    def implements(cls, what: type):
        @mutex(cls.__class_mutex__)
        def wrapper(impl):
            cls._interface_resolver.implement(what, impl)
            return impl
        return wrapper

    @threadsafe
    @classmethod
    def isinterface(cls, tp: type) -> bool:
        return cls._interface_resolver.is_interface(tp)

    @threadsafe
    @classmethod
    def is_singleton(cls, target: type) -> bool:
        return target in cls._singletons_available