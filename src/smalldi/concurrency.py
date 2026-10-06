import functools
import inspect
import threading
from typing import Callable, Type

_LOCK_ATTR = "_threadsafe_lock"


def threadsafe_fn(func):
    """
    Makes function threadsafe: all calls of the function are serialized with a single
    reentrant lock, so it may call itself recursively.
    :param func: function to make threadsafe
    :return: wrapped function
    """
    lock = threading.RLock()

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with lock:
            return func(*args, **kwargs)
    return wrapper


def _locked_method(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with getattr(self, _LOCK_ATTR):
            return method(self, *args, **kwargs)
    return wrapper


def threadsafe_cls(cls):
    """
    Makes class threadsafe: every instance gets its own reentrant lock, and calls of public
    methods and property accessors defined in the class are serialized on that lock.
    Methods may call each other. Dunder methods, static methods and class methods are not wrapped;
    methods inherited from base classes are not wrapped unless the base is threadsafe itself.
    :param cls: class to make threadsafe
    :return: the same class with methods wrapped
    :raises TypeError: if instances of the class have no __dict__ (all of its __slots__ lack it)
    """
    if not cls.__dictoffset__:
        raise TypeError(f"{cls!r} defines __slots__ without __dict__; "
                        f"add '__dict__' to __slots__ to make it threadsafe")
    for name, attr in list(vars(cls).items()):
        if name.startswith("__") and name.endswith("__"):
            continue
        if inspect.isfunction(attr):
            setattr(cls, name, _locked_method(attr))
        elif isinstance(attr, property):
            setattr(cls, name, property(
                *(_locked_method(f) if f is not None else None
                  for f in (attr.fget, attr.fset, attr.fdel)),
                attr.__doc__,
            ))

    original_init = cls.__init__

    @functools.wraps(original_init)
    def __init__(self, *args, **kwargs):
        # The object isn't shared with other threads until __init__ returns, so this is race-free.
        # setdefault keeps the lock created by a threadsafe subclass calling super().__init__
        self.__dict__.setdefault(_LOCK_ATTR, threading.RLock())
        original_init(self, *args, **kwargs)

    cls.__init__ = __init__
    return cls


def threadsafe(obj: Type | Callable):
    """
    Makes class (see threadsafe_cls) or function (see threadsafe_fn) threadsafe.
    :param obj: class or function
    :return: threadsafe class or function
    """
    if isinstance(obj, type):
        return threadsafe_cls(obj)
    return threadsafe_fn(obj)
