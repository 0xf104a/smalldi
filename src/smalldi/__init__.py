"""
Annotation-driven dependency injection.

`Injector` registers classes as singletons and abstract classes as interfaces,
binds them to each other with overrides and implementations, and fills the
parameters of `@Injector.inject`-decorated functions that are annotated with
`Provide[T]`. Singletons are instantiated on first use, at most once each.

Public names: `Injector`, `Provide` and `SingletonFrozenError`.
"""
import functools
import threading
import types
import warnings
from inspect import isabstract
from typing import Any, Callable

from smalldi._interfaces import InterfaceResolver
from smalldi._singleton import LazySingleton, SingletonFrozenError
from smalldi.annotation import _Provide, Provide
from smalldi.concurrency import threadsafe, mutex
from smalldi.decorator import staticclass

__author__ = "Anna-Sofia Kasierocka"
__email__ = "f104a@f104a.io"
__version__ = "0.3.0"
__all__ = ["Injector", "Provide", "SingletonFrozenError"]


class _SingletonsAvailable:
    """
    Descriptor behind the deprecated `Injector.singletons_available` class attribute.

    Every read emits a `DeprecationWarning` and returns a read-only snapshot,
    a `types.MappingProxyType`, mapping each registered singleton class to the
    object `Injector.get_instance` returns for it. Building the snapshot
    instantiates every registered singleton that has no instance yet and
    freezes all of them, so none can be overridden afterwards. An overridden
    class maps to its override's instance. Interfaces are not included.

    The list of registered classes is copied while holding the injector's
    class mutex; the instances are then requested outside the lock, one
    `Injector.get_instance` call per class. Assigning to an item of the
    snapshot raises `TypeError`.

    :raises RuntimeError: from `Injector.get_instance`, if a constructor forms a circular dependency
    :raises Exception: any exception raised by a singleton constructor propagates unchanged;
        singletons instantiated before it stay instantiated and frozen
    """

    def __get__(self, obj, owner):
        """
        :param obj: None for class-level access, which is the only supported form
        :param owner: the `Injector` class
        :return: read-only mapping of registered singleton classes to their instances
        """
        warnings.warn(
            "Injector.singletons_available is deprecated and will be removed in 1.0.0; "
            "inject singletons with Provide[T] instead",
            DeprecationWarning,
            stacklevel=2,
        )
        with owner.__class_mutex__:
            classes = list(owner._singletons_available)
        return types.MappingProxyType({cls: owner.get_instance(cls) for cls in classes})


@staticclass
class Injector:
    """
    Static registry of singletons and interfaces, and the injector of their instances.

    `Injector` can't be instantiated: all of its state is kept at class level.
    Classes are registered with `@Injector.singleton`, abstract classes with
    `@Injector.interface`. A singleton declares that it implements an interface
    with `@Injector.implements`, and replaces an interface's implementation or
    another singleton with `@Injector.override`; both decorators go above
    `@Injector.singleton`. Functions decorated with `@Injector.inject` receive
    the instance for every parameter annotated with `Provide[T]`, where `T` is
    a registered singleton or interface.

    Instances are created on first use, at most once per singleton, through
    `Injector.get_instance`. Asking for an instance freezes the singleton or
    interface, so it can't be overridden afterwards. Overrides are not
    transitive: an override can't be overridden, and an overridden singleton
    can't become an override.

    Every registered singleton is held by one `LazySingleton` in
    `_singletons_available`, and every interface by an `InterfaceResolver`
    entry that refers to those `LazySingleton` objects.

    Locking. The reentrant class mutex `__class_mutex__` guards the registry:
    `singleton`, `interface`, `override`, `implements`, `is_singleton` and
    `is_interface` hold it for the whole call through `@threadsafe`; `inject`
    takes it while it checks each `Provide[T]` parameter at decoration time;
    the decorators returned by `override` and `implements` hold it while they
    bind, which also briefly takes the state lock of each `LazySingleton` and
    interface binding involved. `get_instance` holds the class mutex only to
    look the singleton or interface binding up and releases it before any
    instance is requested. A constructor runs under its singleton's build
    lock only, so no lock that guards the registry or a binding is ever held
    while a constructor runs. A deadlock is still possible when threads wait
    for each other across constructors: a dependency cycle spanning several
    threads, or a constructor waiting for a thread that needs the singleton
    being constructed. Neither is detected.

    `Injector.singletons_available` is deprecated: reading it warns, returns a
    read-only mapping of every registered singleton class to its instance, and
    freezes all of them. See `_SingletonsAvailable`.
    """
    # Guarded by __class_mutex__: every method that reads or writes these holds
    # it, through @threadsafe, `with cls.__class_mutex__` or @mutex. The mutex
    # is reentrant and is never held while an instance is requested.
    _singletons_available: dict[type, LazySingleton] = dict()
    _interface_resolver = InterfaceResolver()
    __class_mutex__ = threading.RLock()

    singletons_available = _SingletonsAvailable()

    @classmethod
    def get_instance(cls, tp: type) -> Any:
        """
        Returns the instance to inject for a registered singleton or interface, creating it if needed.

        Follows the interface's override or implementation and the singleton's
        override, and freezes every singleton and interface on the way, so none
        of them can be overridden afterwards. The class mutex is held only while
        the singleton or interface binding is looked up.

        :param tp: registered singleton class or interface
        :return: the instance
        :raises KeyError: if `tp` is neither a registered singleton nor a registered interface
        :raises RuntimeError: if `tp` is an interface with neither an implementation nor an override
        :raises RuntimeError: if the singleton is re-entered by its own constructor, directly or
            through its dependencies (circular dependency)
        :raises Exception: any exception raised by the constructor propagates unchanged
        """
        with cls.__class_mutex__:
            if cls._interface_resolver.is_interface(tp):
                binding = cls._interface_resolver.get_binding(tp)
            else:
                binding = cls._singletons_available[tp]
        if isinstance(binding, LazySingleton):
            return binding.get_instance()
        return binding.get_impl()

    @classmethod
    def inject(cls, fn):
        """
        Makes a function receive the instance of every parameter annotated with `Provide[T]`.

        Each such parameter is filled with `Injector.get_instance(T)` on every
        call, unless the caller passes that argument by keyword. If `T` is an
        interface, the instance of its override or implementation is passed;
        if `T` is overridden, the override's instance is passed. Nothing is
        instantiated at decoration time, so overrides declared before the first
        call are respected.

        Every `T` must be a registered singleton or interface when the function
        is decorated. An interface doesn't need a binding yet: it needs one by
        the time the function is called. Dependencies passed positionally aren't
        detected: the parameter is filled by keyword as well, so the call raises
        `TypeError` for a duplicate argument.

        :param fn: function to inject dependencies into
        :return: wrapper of `fn` with the same signature
        :raises TypeError: at decoration, if a `Provide[T]` parameter names neither a registered
            singleton nor a registered interface
        :raises RuntimeError: at call time, if an injected interface has no binding, or a
            constructor forms a circular dependency
        :raises Exception: at call time, any exception raised by a constructor propagates unchanged
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
        """
        Registers a class as a singleton, to be instantiated on first use.

        The class is not instantiated here. Its constructor is called by
        `Injector.get_instance` the first time an instance is needed, and must
        work without arguments, or be decorated with `@Injector.inject` so that
        its parameters are provided.

        :param target_cls: class to register
        :return: `target_cls`, unchanged
        :raises TypeError: if `target_cls` is abstract, or is already registered
        """
        if isabstract(target_cls):
            raise TypeError(f"Class {target_cls} is abstract and cannot be a singleton. Maybe you meant to use @Injector.interface instead?")
        if target_cls in cls._singletons_available:
            raise TypeError(f"Class {target_cls} is already a singleton")
        cls._singletons_available[target_cls] = LazySingleton(target_cls)
        return target_cls

    @threadsafe
    @classmethod
    def _override_singleton(cls, source_cls):
        """
        Returns the decorator that makes a registered singleton override `source_cls`.

        The decorator validates everything before binding anything: on failure
        neither singleton changes.

        :param source_cls: registered singleton to override
        :return: decorator taking the overriding class and returning it unchanged
        :raises TypeError: from the decorator, if `source_cls` or the overriding class is not a
            registered singleton, the overriding class is not a subclass of `source_cls`,
            both are the same class, `source_cls` is an override itself, or the overriding
            class is already overridden
        :raises SingletonFrozenError: from the decorator, if `source_cls` is frozen
        :raises RuntimeError: from the decorator, if `source_cls` is already overridden
        """
        @mutex(cls.__class_mutex__)
        def wrapper(new_cls):
            if source_cls not in cls._singletons_available:
                raise TypeError(
                    f"Class {source_cls.__name__} is not a known singleton. "
                    f"You must override an existing singleton."
                )
            if new_cls not in cls._singletons_available:
                raise TypeError(
                    f"Class {new_cls.__name__} is not a singleton: "
                    f"apply @Injector.override above @Injector.singleton"
                )
            if not issubclass(new_cls, source_cls):
                raise TypeError(f"{new_cls.__name__} is not a subclass of {source_cls.__name__}")
            target = cls._singletons_available[source_cls]
            target.delegate_to(cls._singletons_available[new_cls])
            return new_cls
        return wrapper

    @threadsafe
    @classmethod
    def _override_interface(cls, interface):
        """
        Returns the decorator that makes a registered singleton override `interface`.

        :param interface: registered interface to override
        :return: decorator taking the overriding class and returning it unchanged
        :raises TypeError: from the decorator, if the overriding class is not a registered
            singleton, not a subclass of `interface`, already overridden, or the
            interface's implementation, or if `interface` is already overridden
        :raises SingletonFrozenError: from the decorator, if `interface` is frozen
        """
        @mutex(cls.__class_mutex__)
        def wrapper(new_impl):
            if new_impl not in cls._singletons_available:
                raise TypeError(
                    f"Class {new_impl.__name__} is not a singleton: "
                    f"apply @Injector.override above @Injector.singleton"
                )
            cls._interface_resolver.override(interface, new_impl, cls._singletons_available[new_impl])
            return new_impl
        return wrapper

    @threadsafe
    @classmethod
    def interface(cls, target_cls):
        """
        Registers an abstract class as an interface that singletons may implement or override.

        :param target_cls: abstract class (an `abc.ABC` subclass with at least one abstract method)
        :return: `target_cls`, unchanged
        :raises TypeError: if `target_cls` is not abstract, or is already registered as an interface
        """
        if not isabstract(target_cls):
            raise TypeError(f"Class {target_cls} is not abstract and cannot be an interface. Maybe you meant to use @Injector.singleton instead?")
        cls._interface_resolver.register(target_cls)
        return target_cls

    @threadsafe
    @classmethod
    def override(cls, what: type, when: Callable[[], bool] = lambda: True):
        """
        Returns the decorator that makes a registered singleton injected instead of `what`.

        Apply the decorator above `@Injector.singleton`. `what` may be a
        registered interface, whose implementation (if any) is then never
        injected through it, or a registered singleton, which then shares the
        override's instance and is never instantiated through the injector.
        Overrides are not transitive: an override can't be overridden and an
        overridden singleton can't become an override. Each target is
        overridden at most once, and a frozen target can't be overridden.

        :param what: registered interface or singleton to override
        :param when: A function returning True if the override should be applied
        :return: decorator taking the overriding class and returning it unchanged
        :raises TypeError: from the decorator, if `what` is not registered, the overriding class
            is not a registered singleton or not a subclass of `what`, the override would form
            a chain, a class overrides itself, an interface is overridden twice, or the
            overriding class is the interface's implementation
        :raises SingletonFrozenError: from the decorator, if `what` is frozen
        :raises RuntimeError: from the decorator, if `what` is a singleton that is already overridden
        """
        if not when():
            return lambda candidate: candidate
        if cls._interface_resolver.is_interface(what):
            return cls._override_interface(what)
        else:
            return cls._override_singleton(what)

    @threadsafe
    @classmethod
    def implements(cls, what: type):
        """
        Returns the decorator that declares a registered singleton as the implementation of interface `what`.

        Apply the decorator above `@Injector.singleton`. `Provide[what]` then
        receives the implementation's instance, unless the interface is
        overridden, in which case the override's instance is injected and the
        implementation is never instantiated through the interface. An
        interface has at most one implementation.

        :param what: registered interface
        :return: decorator taking the implementing class and returning it unchanged
        :raises TypeError: from the decorator, if the implementing class is not a registered
            singleton, `what` is not a registered interface, the class is not a subclass of
            `what`, or the class is the interface's override
        :raises RuntimeError: from the decorator, if `what` already has an implementation
        :raises SingletonFrozenError: from the decorator, if `what` is frozen and has no override
        """
        @mutex(cls.__class_mutex__)
        def wrapper(impl):
            if impl not in cls._singletons_available:
                raise TypeError(
                    f"Class {impl.__name__} is not a singleton: "
                    f"apply @Injector.implements above @Injector.singleton"
                )
            cls._interface_resolver.implement(what, impl, cls._singletons_available[impl])
            return impl
        return wrapper

    @threadsafe
    @classmethod
    def is_interface(cls, tp: type) -> bool:
        """
        Tells whether a class is registered as an interface.

        :param tp: class to check
        :return: True if `tp` was registered with `@Injector.interface`
        """
        return cls._interface_resolver.is_interface(tp)

    @threadsafe
    @classmethod
    def is_singleton(cls, target: type) -> bool:
        """
        Tells whether a class is registered as a singleton.

        :param target: class to check
        :return: True if `target` was registered with `@Injector.singleton`
        """
        return target in cls._singletons_available