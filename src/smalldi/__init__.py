import functools
from threading import RLock
import warnings

from smalldi.wrappers import staticclass
from smalldi.annotation import _Provide, Provide
from smalldi._interface import InterfaceTable, InterfaceFrozenError, InterfaceAlreadyBoundError
from smalldi._singleton import LazySingleton

__author__ = "Anna-Sofia Kasierocka"
__email__ = "f104a@f104a.io"
__version__ = "0.3.0"
__all__ = ["Injector", "Provide", "InterfaceFrozenError", "InterfaceAlreadyBoundError"]

class _InjectorMeta(type):
    @property
    def singletons_available(cls):
        """
        Deprecated read-only snapshot of singleton instances which were already created.
        Singletons are created lazily, so ones which were not injected yet are missing.
        """
        warnings.warn("Using Injector.singletons_available is deprecated as it is not thread-safe; "
                      "it contains only singletons which were already created. "
                      "Use Injector.inject instead.", DeprecationWarning, stacklevel=2)
        with cls._mutex:
            singletons = dict(cls._singletons_available)
        instances = {tp: singleton.instance for tp, singleton in singletons.items()}
        return {tp: instance for tp, instance in instances.items() if instance is not None}


@staticclass
class Injector(metaclass=_InjectorMeta):
    """
    The injector class handles all the dependency injections.
    """
    _singletons_available: dict[type, LazySingleton] = {}
    _interfaces = InterfaceTable()
    _mutex = RLock()

    @classmethod
    def inject(cls, fn):
        """
        Injects dependencies into function.
        Dependencies are resolved on the first call which doesn't pass them explicitly,
        so singletons and interfaces may be declared and bound after the function.
        :param fn: function to inject dependencies into
        :return: function with injected dependencies
        """
        dependencies = dict(_Provide.iter_annotations(fn))
        # Resolved dependencies are frozen, so caching them is safe; racing threads store the same value
        resolved = {}

        @functools.wraps(fn)
        def wrapped_fn(*args, **kwargs):
            for name, tp in dependencies.items():
                if name not in kwargs:
                    if name not in resolved:
                        resolved[name] = cls._resolve(tp)
                    kwargs[name] = resolved[name]
            return fn(*args, **kwargs)

        return wrapped_fn

    @classmethod
    def singleton(cls, target_cls):
        """
        Marks class as singleton.
        Singleton classes are instantiated only once by the injector, when first injected.
        Also their __init__ function should have no arguments or be annotated
        with @Injector.inject, so it would
        :param target_cls: Class which to be marked as injectable singleton
        :return: target_cls unaltered
        :raises ValueError: if class is already a singleton
        :raises TypeError: if class is used as an interface
        """
        with cls._mutex:
            if target_cls in cls._singletons_available:
                raise ValueError("Class is already marked as singleton")
            if cls._interfaces.is_declared(target_cls):
                raise TypeError(f"{target_cls!r} is an interface; it cannot be a singleton")
            cls._singletons_available[target_cls] = LazySingleton(target_cls)
        return target_cls

    @classmethod
    def implements(cls, interface):
        """
        Binds singleton class to interface as its baseline implementation,
        so Provide[interface] injects its instance. Must be applied above @Injector.singleton.
        An interface has exactly one baseline; use @Injector.override to replace it.
        :param interface: interface (usually an abstract class) implemented by the class
        :return: decorator which binds the class and returns it unaltered
        """
        return cls._binder(interface, cls._interfaces.set_interface_impl, "implements")

    @classmethod
    def override(cls, interface, on=lambda: True):
        """
        Overrides the baseline implementation of interface with singleton class.
        Must be applied above @Injector.singleton. An interface may be overridden only once,
        before it is first injected; the override may be declared before or after the baseline.
        :param interface: interface (usually an abstract class) implemented by the class;
            it must not be a singleton itself
        :param on: predicate called once at decoration time; if it returns false,
            the override is skipped and the class is left unbound. The class is validated either way
        :return: decorator which binds the class and returns it unaltered
        """
        if not callable(on):
            raise TypeError(f"{on!r} is not callable")
        if on():
            return cls._binder(interface, cls._interfaces.set_interface_override, "override")
        return cls._binder(interface, None, "override")

    @classmethod
    def _binder(cls, interface, bind, decorator_name):
        """
        :param bind: binds the class to the interface; None only validates the binding
        """
        def _wrapper(target_cls):
            InterfaceTable.check_impl(interface, target_cls)
            with cls._mutex:
                if target_cls not in cls._singletons_available:
                    raise TypeError(f"{target_cls!r} must be a singleton to implement an interface; "
                                    f"apply @Injector.{decorator_name} above @Injector.singleton")
                if interface in cls._singletons_available:
                    raise TypeError(f"{interface!r} is a singleton; it cannot be used as an interface "
                                    f"in @Injector.{decorator_name}")
                # Reserve the key under the mutex, so it can't concurrently become a singleton
                cls._interfaces.declare(interface)
            if bind is not None:
                bind(interface, target_cls)
            return target_cls
        return _wrapper

    @classmethod
    def _resolve(cls, tp):
        # Don't hold the mutex while creating: singleton __init__ may resolve its own dependencies
        with cls._mutex:
            singleton = cls._singletons_available.get(tp)
        if singleton is None:
            impl = cls._interfaces.get_interface_impl(tp)
            if impl is None:
                raise TypeError(f"Singleton {tp} is not available")
            with cls._mutex:
                singleton = cls._singletons_available[impl]
        return singleton.get()
