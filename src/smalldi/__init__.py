import functools
import warnings

from smalldi.wrappers import staticclass
from smalldi.annotation import _Provide, Provide
from smalldi._interface import InterfaceTable, InterfaceFrozenError, InterfaceAlreadyBoundError

__author__ = "Anna-Sofia Kasierocka"
__email__ = "f104a@f104a.io"
__version__ = "0.3.0"
__all__ = ["Injector", "Provide", "InterfaceFrozenError", "InterfaceAlreadyBoundError"]

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
    _interfaces = InterfaceTable()

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
        cls._singletons_available[target_cls] = target_cls()
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
        :param interface: interface (usually an abstract class) implemented by the class
        :param on: predicate called once at decoration time; if it returns false,
            the override is skipped and the class is left unbound
        :return: decorator which binds the class and returns it unaltered
        """
        if not callable(on):
            raise TypeError(f"{on!r} is not callable")
        if on():
            return cls._binder(interface, cls._interfaces.set_interface_override, "override")
        return lambda target_cls: target_cls

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
    def _resolve(cls, tp):
        if tp in cls._singletons_available:
            return cls._singletons_available[tp]
        impl = cls._interfaces.get_interface_impl(tp)
        if impl is not None:
            return cls._singletons_available[impl]
        raise TypeError(f"Singleton {tp} is not available")
