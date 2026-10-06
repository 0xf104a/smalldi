import functools
import inspect
import threading
import warnings
from enum import Enum, auto
from typing import Any, Callable

_INSTANCE_MUTEX_ATTR = "__instance_mutex__"
_CLASS_MUTEX_ATTR = "__class_mutex__"
_INSTALL_LOCK = threading.Lock()


class _FunctionPlacement(Enum):
    INSTANCE_LEVEL = auto()
    CLASS_LEVEL = auto()
    STATIC_LEVEL = auto()

    @classmethod
    def from_function(cls, fn: object) -> "_FunctionPlacement | None":
        if isinstance(fn, staticmethod):
            return cls.STATIC_LEVEL
        if isinstance(fn, classmethod):
            return cls.CLASS_LEVEL
        if inspect.isfunction(fn):
            # Plain function: either a def directly in a class body (instance-level)
            # or a module-level / nested function that isn't a method at all.
            parent, _, _ = fn.__qualname__.rpartition(".")
            if parent and not parent.endswith("<locals>"):
                return cls.INSTANCE_LEVEL
            return None
        return None


def _reject_async(fn: Callable, decorator: str) -> None:
    if inspect.iscoroutinefunction(fn) or inspect.isasyncgenfunction(fn):
        raise NotImplementedError(
            f"@{decorator} does not support async functions yet: "
            f"{getattr(fn, '__qualname__', fn)!r}"
        )


def synchronized(fn: Callable) -> Callable:
    _reject_async(fn, "synchronized")
    mutex = threading.RLock()

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with mutex:
            return fn(*args, **kwargs)

    return wrapper


def _get_mutex_for_class(cls: type) -> threading.RLock:
    # vars(), not getattr(): a subclass must not inherit its parent's mutex
    mutex = vars(cls).get(_CLASS_MUTEX_ATTR)
    if mutex is not None:
        return mutex
    with _INSTALL_LOCK:
        mutex = vars(cls).get(_CLASS_MUTEX_ATTR)
        if mutex is None:
            mutex = threading.RLock()
            type.__setattr__(cls, _CLASS_MUTEX_ATTR, mutex)
        return mutex


def _get_mutex_for_object(obj: Any) -> threading.RLock:
    # object.__getattribute__/__setattr__ bypass user-defined hooks
    # (proxies with __getattr__, frozen dataclasses)
    try:
        return object.__getattribute__(obj, _INSTANCE_MUTEX_ATTR)
    except AttributeError:
        pass
    with _INSTALL_LOCK:
        try:
            return object.__getattribute__(obj, _INSTANCE_MUTEX_ATTR)
        except AttributeError:
            mutex = threading.RLock()
            try:
                object.__setattr__(obj, _INSTANCE_MUTEX_ATTR, mutex)
            except AttributeError as e:
                raise TypeError(
                    f"{type(obj).__qualname__} has no __dict__; "
                    f"add {_INSTANCE_MUTEX_ATTR!r} to __slots__"
                ) from e
            return mutex


def threadsafe(fn: Any) -> Any:
    _reject_async(getattr(fn, "__func__", fn), "threadsafe")
    placement = _FunctionPlacement.from_function(fn)

    if placement is None:
        warnings.warn(
            "@threadsafe applied to a function outside a class body; "
            "use @synchronized directly.",
            stacklevel=2,
        )
        return synchronized(fn)

    if placement is _FunctionPlacement.STATIC_LEVEL:
        return staticmethod(synchronized(fn.__func__))

    if placement is _FunctionPlacement.CLASS_LEVEL:
        func = fn.__func__

        @functools.wraps(func)
        def class_wrapper(cls, *args, **kwargs):
            with _get_mutex_for_class(cls):
                return func(cls, *args, **kwargs)

        return classmethod(class_wrapper)

    if placement is _FunctionPlacement.INSTANCE_LEVEL:
        @functools.wraps(fn)
        def instance_wrapper(self, *args, **kwargs):
            with _get_mutex_for_object(self):
                return fn(self, *args, **kwargs)

        return instance_wrapper

    raise RuntimeError("Unknown function placement")
