"""
Decorators serializing calls between threads.

* `@synchronized` guards a function with a single lock shared by all callers.
* `@threadsafe` guards a method with a lock chosen by where it is defined:
  per instance, per class or per function.

Both use reentrant locks, so a guarded function may call itself or other
functions guarded by the same lock. Async functions aren't supported yet.
Generator functions are accepted, but the lock is held only while the
generator object is created, not while it is iterated.
"""
import functools
import inspect
import threading
import warnings
from contextlib import AbstractContextManager
from enum import Enum, auto
from typing import Any, Callable

_INSTANCE_MUTEX_ATTR = "__instance_mutex__"
_CLASS_MUTEX_ATTR = "__class_mutex__"
_INSTALL_LOCK = threading.Lock()


class _FunctionPlacement(Enum):
    """
    Where a function decorated with `@threadsafe` is defined, which determines
    the lock guarding it.
    """
    INSTANCE_LEVEL = auto()
    CLASS_LEVEL = auto()
    STATIC_LEVEL = auto()

    @classmethod
    def from_function(cls, fn: object) -> "_FunctionPlacement | None":
        """
        Detects the placement of a function from the object found in the class body.
        Plain functions are told apart by `__qualname__`: a function defined
        directly in a class body is an instance method.

        :param fn: function, `staticmethod` or `classmethod` object
        :return: placement of the function, or None if it isn't defined in a class body
        """
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
    """
    Rejects coroutine functions and async generator functions: a lock held
    while calling them would be released before their body runs.

    :param fn: function to check
    :param decorator: name of the decorator, used in the error message
    :raises NotImplementedError: if `fn` is async
    """
    if inspect.iscoroutinefunction(fn) or inspect.isasyncgenfunction(fn):
        raise NotImplementedError(
            f"@{decorator} does not support async functions yet: "
            f"{getattr(fn, '__qualname__', fn)!r}"
        )


def synchronized(fn: Callable) -> Callable:
    """
    Guards a function with its own reentrant lock, so only one thread at a time
    may execute it. The lock is shared by every caller: for methods this means
    all instances and classes share it. Use `@threadsafe` for a per-instance
    or per-class lock.

    :param fn: function to guard
    :return: guarded function
    :raises NotImplementedError: if `fn` is a coroutine function or an async generator function
    """
    _reject_async(fn, "synchronized")
    mutex = threading.RLock()

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with mutex:
            return fn(*args, **kwargs)

    return wrapper


def _get_mutex_for_class(cls: type) -> threading.RLock:
    """
    Returns the lock of a class, creating it on the first call.
    The lock is stored on the class itself, and subclasses get their own.

    :param cls: class to get the lock of
    :return: the class lock
    """
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
    """
    Returns the lock of an object, creating it on the first call.
    The lock is stored in the object's `__dict__` as `__instance_mutex__`,
    which makes the object impossible to pickle or deep-copy.

    :param obj: object to get the lock of
    :return: the object lock
    :raises TypeError: if `obj` has no `__dict__` and no `__instance_mutex__` slot
    """
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
    """
    Guards a method with a reentrant lock chosen by where it is defined:

    * instance methods lock per instance, so different instances don't block
      each other. All `@threadsafe` methods of one instance share its lock;
    * `@classmethod` methods lock per class the method is called on. All
      `@threadsafe` class methods of one class share its lock, and a subclass
      gets its own lock, separate from its parent's;
    * `@staticmethod` methods lock per function, like `@synchronized`.

    Apply it on top of `@classmethod` and `@staticmethod`. Applied to a
    function outside a class body, it warns and falls back to `@synchronized`.

    Instance locks are stored in the instance `__dict__`. Classes using
    `__slots__` must list `__instance_mutex__` in their slots, and instances
    can't be pickled or deep-copied once a guarded method ran, unless
    `__getstate__` drops the lock.

    :param fn: function, `classmethod` or `staticmethod` defined in a class body
    :return: guarded function of the same kind
    :raises NotImplementedError: if `fn` is a coroutine function or an async generator function
    """
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

def mutex(fn_mutex: AbstractContextManager): # makes function to run within mutex
    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with fn_mutex:
                return fn(*args, **kwargs)

        return wrapper

    return decorate
