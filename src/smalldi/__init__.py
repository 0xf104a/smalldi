import functools
import threading
import warnings
from inspect import isabstract
from types import MappingProxyType
from typing import Any, Mapping

from smalldi._interfaces import InterfaceResolver, LazyInterfaceImpl
from smalldi._singleton import LazySingleton, SingletonFrozenError, atomic
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

        An overridden singleton maps to its override's instance, the same one
        `Provide[Singleton]` receives; the overridden class itself is never
        instantiated.

        The snapshot doesn't follow later changes: singletons registered after
        reading it are not included. Read the property again to see them.
        Instantiation happens outside the registry lock, so singleton
        constructors may register or inject other singletons.

        :return: read-only mapping of singleton class to its instance
        """
        with cls._registry_lock:
            registered = list(cls._singletons_available.items())
            interfaces = list(cls._interface_resolver.bindings())
        instances = MappingProxyType({tp: s.get_instance() for tp, s in registered})
        # Freezes the interfaces; their instances were created above already
        for interface in interfaces:
            if interface.resolvable:
                interface.get_instance()
        return instances

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
    `Provide[Interface]` then receives that singleton's instance. Both
    interfaces and singletons may be replaced with `@Injector.override`.

    Every registered singleton is held by a `LazySingleton` and every
    interface by a `LazyInterfaceImpl`. They know what they delegate to (an
    override, an implementation) and whether they are frozen; the injector
    only looks them up and binds them.

    Registration and lookups are guarded by a reentrant lock, so the injector
    may be used from several threads. Singletons are instantiated lazily, at
    most once each.
    """
    # Not threadsafe on their own: access only while holding _registry_lock
    _singletons_available: dict[type, LazySingleton] = dict()
    _interface_resolver = InterfaceResolver()
    _registry_lock = threading.RLock()

    @classmethod
    def _lookup(cls, tp: type) -> LazySingleton | LazyInterfaceImpl:
        """
        Returns the `LazySingleton` registered for a singleton class, or the
        `LazyInterfaceImpl` of an interface. Must be called while holding
        `_registry_lock`.

        :param tp: registered singleton class or interface
        :return: its singleton or interface binding
        :raises TypeError: if `tp` is neither a registered singleton nor an interface
        """
        singleton = cls._singletons_available.get(tp)
        if singleton is not None:
            return singleton
        if cls._interface_resolver.is_interface(tp):
            return cls._interface_resolver.resolve(tp)
        raise TypeError(f"Singleton {tp} is not available")

    @classmethod
    def _get_instance(cls, tp: type) -> Any:
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
        with cls._registry_lock:
            singleton = cls._lookup(tp)
        # Outside the lock: a constructor must not block the whole registry
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
        the singleton is frozen and can't be overridden, even if creating the
        instance failed.

        A class can be registered only once. Registering it again, or
        registering a class with the same module and qualified name (as happens
        after `importlib.reload`), raises `TypeError`: the injector is set up
        once per process.

        :param target_cls: Class which to be marked as injectable singleton
        :return: `target_cls` unchanged, so this may be used as a decorator
        :raises TypeError: if `target_cls` is abstract, is an interface, or is
            already registered (possibly as a reloaded class)
        """
        if isabstract(target_cls):
            raise TypeError(f"Class {target_cls} is abstract and cannot be a singleton")
        with cls._registry_lock:
            if cls._interface_resolver.is_interface(target_cls):
                raise TypeError(f"Class {target_cls} is an interface and cannot be a singleton")
            if any(_same_class(tp, target_cls) for tp in cls._singletons_available):
                raise TypeError(
                    f"Class {target_cls} is already registered as a singleton (module reload?)"
                )
            cls._singletons_available[target_cls] = LazySingleton(target_cls)
        return target_cls

    @classmethod
    def interface(cls, target_cls):
        """
        Marks class as an interface.

        Interfaces may be injected with `Provide[Interface]` once a singleton
        declares that it implements them with `@Injector.implements` or
        overrides them with `@Injector.override`. An interface must be an
        abstract class, so it can't be a singleton itself.

        An interface can be registered only once. Registering it again, or
        registering a class with the same module and qualified name (as happens
        after `importlib.reload`), raises `TypeError`.

        :param target_cls: abstract class which to be marked as an interface
        :return: `target_cls` unchanged, so this may be used as a decorator
        :raises TypeError: if `target_cls` isn't abstract, is a registered
            singleton, or is already registered (possibly as a reloaded class)
        """
        if not isabstract(target_cls):
            raise TypeError(f"Class {target_cls} is not abstract and cannot be an interface")
        with cls._registry_lock:
            if target_cls in cls._singletons_available:
                raise TypeError(f"Class {target_cls} is a singleton and cannot be an interface")
            if any(_same_class(tp, target_cls) for tp in cls._interface_resolver.interfaces()):
                raise TypeError(
                    f"Class {target_cls} is already registered as an interface (module reload?)"
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
        same class is a no-op. Either all interfaces are bound or, on error,
        none of them.

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
            with cls._registry_lock, atomic():
                singleton = cls._check_binding("implements", target_cls, interfaces)
                bound = [cls._interface_resolver.resolve(interface) for interface in interfaces]
                for interface in bound:
                    interface.check_implementation(singleton)
                for interface in bound:
                    interface.implement(singleton)
            return target_cls

        return decorator

    @classmethod
    def override(cls, *targets):
        """
        Replaces interfaces or singletons with another singleton.

        Returns a decorator to apply above `@Injector.singleton`::

            @Injector.override(Storage)       # an interface
            @Injector.singleton
            class FakeStorage(Storage):
                ...

            @Injector.override(MailService)   # a singleton
            @Injector.singleton
            class FakeMailService(MailService):
                ...

        `Provide[Storage]` then receives the `FakeStorage` instance, and
        `Provide[MailService]` the `FakeMailService` instance: the same objects
        `Provide[FakeStorage]` and `Provide[FakeMailService]` receive. The
        overridden singleton is never instantiated through the injector.

        An interface override may be declared before or after the interface
        implementation: it wins either way, so modules may be imported in any
        order. The implementation stays registered as a singleton, so
        `Provide[Implementation]` still receives it, unless the implementation
        is itself overridden. Overrides are followed transitively: if
        `FakeMailService` is overridden too, both `Provide[MailService]` and
        `Provide[FakeMailService]` receive the last override's instance.

        Each target may have only one override, so it is unambiguous which
        singleton gets injected; declaring it again for the same class is a
        no-op. A target is frozen once an instance was requested through it,
        after which it can't be overridden: an interface once
        `Provide[Interface]` was resolved, a singleton once it was injected
        directly or through an interface it implements, `Injector.singletons`
        was read, or a component was registered in it (containers). A target
        is frozen even if creating its instance failed. Declare overrides
        before the first injection.

        Every target must be a registered interface or singleton, and a base
        class of the overriding singleton. Either all targets are overridden
        or, on error, none of them.

        :param targets: interfaces and singletons to override with the singleton
        :return: decorator applying the overrides and returning the class unchanged
        :raises TypeError: if no targets are given; the decorator raises it if
            the class isn't a registered singleton, a target is neither a
            registered interface nor a singleton, is the class itself or isn't a
            base class of it, or a target is already overridden by another class
        :raises SingletonFrozenError: raised by the decorator if a target was
            already injected
        """
        if not targets:
            raise TypeError("@Injector.override requires at least one interface or singleton")

        def decorator(target_cls):
            with cls._registry_lock, atomic():
                singleton = cls._check_binding("override", target_cls, targets, allow_singletons=True)
                overridden = [cls._lookup(target) for target in targets]
                for target in overridden:
                    target.check_override(singleton)
                for target in overridden:
                    target.override(singleton)
            return target_cls

        return decorator

    @classmethod
    def _check_binding(
        cls,
        decorator: str,
        target_cls: type,
        targets: tuple[type, ...],
        allow_singletons: bool = False,
    ) -> LazySingleton:
        """
        Checks that a singleton and the interfaces (or, with `allow_singletons`,
        singletons) to bind it to are registered. The binding rules themselves
        are checked by `LazySingleton`. Must be called while holding
        `_registry_lock`.

        :param decorator: name of the calling decorator, used in error messages
        :param target_cls: class to bind
        :param targets: interfaces (and singletons) to bind the class to
        :param allow_singletons: whether registered singletons are accepted besides interfaces
        :return: the singleton registered for `target_cls`
        :raises TypeError: if `target_cls` isn't a registered singleton, or a
            target isn't a registered interface (or singleton)
        """
        singleton = cls._singletons_available.get(target_cls)
        if singleton is None:
            raise TypeError(
                f"Class {target_cls} is not a singleton; "
                f"apply @Injector.{decorator} above @Injector.singleton"
            )
        for target in targets:
            if cls._interface_resolver.is_interface(target):
                continue
            if not allow_singletons:
                raise TypeError(f"Class {target} is not an interface")
            if target not in cls._singletons_available:
                raise TypeError(f"Class {target} is neither an interface nor a singleton")
        return singleton
