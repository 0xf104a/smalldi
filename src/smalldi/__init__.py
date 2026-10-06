import functools
import threading
import warnings

from smalldi.wrappers import staticclass
from smalldi.annotation import _Provide, Provide
from smalldi._interface import InterfaceTable, InterfaceFrozenError, InterfaceAlreadyBoundError
from smalldi._singleton import SingletonFrozenException

__author__ = "Anna-Sofia Kasierocka"
__email__ = "f104a@f104a.io"
__version__ = "0.3.0"
__all__ = ["Injector", "Provide", "InterfaceFrozenError", "InterfaceAlreadyBoundError",
           "SingletonFrozenException"]

class _InjectorMeta(type):
    @property
    def singletons_available(cls):
        """Deprecated public alias of the singleton registry."""
        warnings.warn("Using Injector.singletons_available is deprecated as it is not thread-safe. "
                      "Use Injector.inject instead.", DeprecationWarning, stacklevel=2)
        return cls._singletons_available


@staticclass
class Injector(metaclass=_InjectorMeta):
    """
    The injector class handles all the dependency injections.
    """
    _singletons_available = {}
    _singleton_overrides = {}
    _singletons_frozen = set()
    _interfaces = InterfaceTable()
    _mutex = threading.RLock()

    @classmethod
    def inject(cls, fn):
        """
        Injects dependencies into function.
        :param fn: function to inject dependencies into
        :return: function with injected dependencies
        """
        kwargs_ext = dict()
        for name, tp in _Provide.iter_annotations(fn):
            kwargs_ext[name] = cls._resolve(tp)

        @functools.wraps(fn)
        def wrapped_fn(*args, **kwargs):
            for name, value in kwargs_ext.items():
                if name not in kwargs:
                    kwargs[name] = value
            return fn(*args, **kwargs)

        return wrapped_fn

    @classmethod
    def singleton(cls, target_cls):
        """
        Marks class as singleton.
        Singleton classes are instantiated only once by the injector.
        Also their __init__ function should have no arguments or be annotated
        with @Injector.inject, so it would
        :param target_cls: Class which to be marked as injectable singleton
        :return: None
        """
        # Look up in own __dict__: subclasses of a singleton (e.g. its overrides) inherit __singleton__
        if vars(target_cls).get("__singleton__") is not None:
            raise ValueError("Class is already marked as singleton")
        instance = target_cls()
        with cls._mutex:
            cls._singletons_available[target_cls] = instance
        target_cls.__singleton__ = instance
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
        Overrides the baseline implementation of interface, or a singleton, with singleton class.
        Must be applied above @Injector.singleton. An interface or singleton may be overridden only
        once, before it is first injected; an interface override may be declared before or after
        the baseline. Overriding a singleton also overrides it wherever it is bound to an interface.
        :param interface: interface (usually an abstract class) implemented by the class,
            or singleton class subclassed by it
        :param on: predicate called once at decoration time; if it returns false,
            the override is skipped and the class is left unbound
        :return: decorator which binds the class and returns it unaltered
        """
        if not callable(on):
            raise TypeError(f"{on!r} is not callable")
        if not on():
            return lambda target_cls: target_cls
        if interface in cls._singletons_available:
            return cls._binder(interface, cls._override_singleton, "override")
        return cls._binder(interface, cls._interfaces.set_interface_override, "override")

    @classmethod
    def _binder(cls, interface, bind, decorator_name):
        def _wrapper(target_cls):
            if target_cls not in cls._singletons_available:
                raise TypeError(f"{target_cls!r} must be a singleton to implement an interface; "
                                f"apply @Injector.{decorator_name} above @Injector.singleton")
            bind(interface, target_cls)
            return target_cls
        return _wrapper

    @classmethod
    def _override_singleton(cls, singleton_cls, override_cls):
        InterfaceTable.check_impl(singleton_cls, override_cls)
        with cls._mutex:
            current = cls._singleton_overrides.get(singleton_cls)
            if current is override_cls:
                return
            if current is not None:
                raise InterfaceAlreadyBoundError(singleton_cls, current, override_cls, "override")
            if singleton_cls in cls._singletons_frozen:
                raise SingletonFrozenException(singleton_cls, override_cls)
            cls._singleton_overrides[singleton_cls] = override_cls

    @classmethod
    def _resolve(cls, tp):
        with cls._mutex:
            target = tp if tp in cls._singletons_available else cls._interfaces.get_interface_impl(tp)
            if target is None:
                raise TypeError(f"Singleton {tp} is not available")
            # Follow singleton overrides, freezing every singleton on the way
            while target is not None:
                cls._singletons_frozen.add(target)
                impl, target = target, cls._singleton_overrides.get(target)
            return cls._singletons_available[impl]
