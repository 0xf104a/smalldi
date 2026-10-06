import functools
import threading
import warnings
from inspect import isabstract
from types import MappingProxyType
from typing import Any, Mapping

from smalldi._singleton import LazySingleton
from smalldi.concurrency import threadsafe
from smalldi.wrappers import staticclass
from smalldi.annotation import _Provide, Provide

__author__ = "Anna-Sofia Kasierocka"
__email__ = "f104a@f104a.io"
__version__ = "0.3.0"
__all__ = ["Injector", "Provide"]

class _InjectorMeta(type):
    @property
    def singletons(cls) -> Mapping[type, Any]:
        """
        Read-only snapshot of all registered singleton instances.
        Instantiates every singleton that wasn't created yet, freezing them
        all: none of them can be overridden afterwards.
        """
        with cls._registry_lock:
            registered = list(cls._singletons_available.items())
        return MappingProxyType({tp: s.get_instance() for tp, s in registered})

    @property
    def singletons_available(cls) -> Mapping[type, Any]:
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
    """
    # Not threadsafe on its own: access only while holding _registry_lock
    _singletons_available: dict[type, LazySingleton] = dict()
    _registry_lock = threading.RLock()

    @classmethod
    def _get_instance(cls, tp: type) -> Any:
        with cls._registry_lock:
            singleton = cls._singletons_available.get(tp)
        if singleton is None:
            raise TypeError(f"Singleton {tp} is not available")
        # Outside the lock: a constructor must not block the whole registry
        return singleton.get_instance()

    @classmethod
    def inject(cls, fn):
        """
        Injects dependencies into function.
        :param fn: function to inject dependencies into
        :return: function with injected dependencies
        """
        name2type = dict()
        for name, tp in _Provide.iter_annotations(fn):
            with cls._registry_lock:
                if tp not in cls._singletons_available:
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
        Singleton classes are instantiated only once by the injector.
        Also their __init__ function should have no arguments or be annotated
        with @Injector.inject, so it would
        :param target_cls: Class which to be marked as injectable singleton
        :return: None
        """
        if isabstract(target_cls):
            raise TypeError(f"Class {target_cls} is abstract and cannot be a singleton")
        with cls._registry_lock:
            if any(
                tp is target_cls
                or (tp.__module__, tp.__qualname__) == (target_cls.__module__, target_cls.__qualname__)
                for tp in cls._singletons_available
            ):
                warnings.warn(
                    f"Class {target_cls} is registered as a singleton more than once "
                    f"(module reload?). Already injected instances are not replaced, "
                    f"so several instances may coexist.",
                    RuntimeWarning,
                    stacklevel=2,
                )
            cls._singletons_available[target_cls] = LazySingleton(target_cls, None)
        return target_cls
