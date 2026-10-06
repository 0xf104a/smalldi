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
        yet, which freezes the whole registry: none of the singletons can be
        overridden afterwards. Avoid reading it before all overrides are done.

        The snapshot doesn't follow later changes: singletons registered after
        reading it are not included. Read the property again to see them.
        Instantiation happens outside the registry lock, so singleton
        constructors may register or inject other singletons.

        :return: read-only mapping of singleton class to its instance
        """
        with cls._registry_lock:
            registered = list(cls._singletons_available.items())
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

    Registration and lookups are guarded by a reentrant lock, so the injector
    may be used from several threads. Singletons are instantiated lazily, at
    most once each.
    """
    # Not threadsafe on its own: access only while holding _registry_lock
    _singletons_available: dict[type, LazySingleton] = dict()
    _registry_lock = threading.RLock()

    @classmethod
    def _get_instance(cls, tp: type) -> Any:
        """
        Returns the instance of a registered singleton, creating it if needed.
        Creating the instance freezes the singleton.

        :param tp: registered singleton class
        :return: the singleton instance
        :raises TypeError: if `tp` isn't registered as a singleton
        """
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

        Every parameter annotated with `Provide[T]` receives the instance of
        singleton `T` when the function is called, unless the caller passes that
        argument explicitly by keyword. Singletons are resolved on each call, not
        at decoration time, so decorating a function doesn't instantiate them,
        and overrides made before the first call are respected.

        All dependencies must already be registered when the function is
        decorated. Dependencies passed positionally aren't detected: pass them
        by keyword to override injection.

        :param fn: function to inject dependencies into
        :return: function with injected dependencies
        :raises TypeError: if a `Provide[T]` dependency isn't a registered singleton
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
        :raises TypeError: if `target_cls` is abstract
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
