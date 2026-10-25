"""
Decorators.
"""
import enum
import functools
import inspect
import threading
import weakref
from typing import Any, Callable, TypeVar, cast, overload


def staticclass(cls):
    """
    Marks a class as static: instantiating it raises `TypeError`.

    The class's `__init__` is replaced by a function that raises, so an
    existing `__init__` is discarded and subclasses inherit the raising one.
    Class attributes, class methods and static methods are unaffected.

    :param cls: class to mark
    :return: `cls`, with its `__init__` replaced
    """
    def _no_init(*_args, **_kwargs):
        raise TypeError("Can't instantiate static class")
    cls.__init__ = _no_init
    return cls

class FunctionPlacement(enum.Enum):
    """
    Where a function decorated with `@threadsafe` is defined, which determines
    the lock guarding it.
    """
    INSTANCE_LEVEL = enum.auto()
    CLASS_LEVEL = enum.auto()
    STATIC_LEVEL = enum.auto()

    @classmethod
    def from_function(cls, fn: object) -> "FunctionPlacement | None":
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

class OneshotLevel(enum.Enum):
    """
    How often a function decorated with `@oneshot` runs.
    """
    PER_CLASS = enum.auto()  # once per class: `cls` of a classmethod, `type(self)` of an instance method
    PER_INSTANCE = enum.auto()  # once per instance; instance methods only
    GLOBAL = enum.auto()  # once everywhere

_Oneshottable = TypeVar("_Oneshottable", bound=Callable | staticmethod | classmethod)


@overload
def oneshot(fn: _Oneshottable, /) -> _Oneshottable: ...


@overload
def oneshot(level: OneshotLevel = ..., /) -> Callable[[_Oneshottable], _Oneshottable]: ...


def oneshot(fn_or_level: Callable | staticmethod | classmethod | OneshotLevel = OneshotLevel.GLOBAL, /) -> Any:
    """
    Marks a function as oneshot: it runs once per level and every later call returns the first result.

    Usable bare (`@oneshot`, which is `GLOBAL`) or with a level
    (`@oneshot(OneshotLevel.PER_CLASS)`; `@oneshot()` is `GLOBAL`). On a
    classmethod or a staticmethod `@oneshot` goes *above* `@classmethod` /
    `@staticmethod`, so it sees the descriptor and knows the first argument
    is the class.

    A call that raises stores nothing: the next call runs the function again.
    A call that re-enters the function for the same key while the first call
    is still running raises `RuntimeError` instead of running it twice. The
    first call runs under the decorator's lock, so concurrent first calls run
    the function once and the others wait for its result.

    Results are kept only as long as their key lives: per-class results are
    dropped with the class, per-instance results with the instance, so
    `PER_INSTANCE` requires instances that support weak references. Instances
    are told apart by identity, so unhashable instances, like non-frozen
    dataclasses, work.

    :param fn_or_level: the function, `staticmethod` or `classmethod` object to mark, for the bare
        form; or the `OneshotLevel`, for the form with parentheses
    :return: the oneshot function, wrapped in the same descriptor it came in; or, when given a level,
        the decorator that makes it
    :raises TypeError: if the level doesn't apply where the function is defined: `PER_INSTANCE`
        outside an instance method, `PER_CLASS` outside a classmethod or an instance method
    """
    if isinstance(fn_or_level, OneshotLevel):
        level = fn_or_level

        def decorator(target: _Oneshottable) -> _Oneshottable:
            return _make_oneshot(target, level)

        # @oneshot(level) / @oneshot(): called with the level, returns the decorator
        return decorator
    # @oneshot: called with the function itself
    return _make_oneshot(fn_or_level, OneshotLevel.GLOBAL)


def _make_oneshot(fn: _Oneshottable, level: OneshotLevel) -> _Oneshottable:
    """
    Validates `level` against the placement of `fn` and wraps it.

    :param fn: function, `staticmethod` or `classmethod` object
    :param level: how often the function runs
    :return: the oneshot wrapper, re-wrapped in the descriptor `fn` came in
    :raises TypeError: see `oneshot`
    """
    placement = FunctionPlacement.from_function(fn)
    name = fn.__func__.__qualname__ if isinstance(fn, (staticmethod, classmethod)) else getattr(fn, "__qualname__", repr(fn))
    if level is OneshotLevel.PER_INSTANCE and placement is not FunctionPlacement.INSTANCE_LEVEL:
        raise TypeError(f"{name}: OneshotLevel.PER_INSTANCE applies only to instance methods")
    if level is OneshotLevel.PER_CLASS and placement not in (FunctionPlacement.CLASS_LEVEL,
                                                             FunctionPlacement.INSTANCE_LEVEL):
        raise TypeError(f"{name}: OneshotLevel.PER_CLASS applies only to classmethods and instance methods")
    if isinstance(fn, (staticmethod, classmethod)):
        return cast(_Oneshottable, type(fn)(_wrap_oneshot(fn.__func__, level, placement)))
    return cast(_Oneshottable, _wrap_oneshot(fn, level, placement))


def _wrap_oneshot(fn: Callable, level: OneshotLevel, placement: "FunctionPlacement | None") -> Callable:
    """
    Builds the oneshot wrapper of a plain function.

    :param fn: the plain function, already unwrapped from its descriptor
    :param level: how often the function runs
    :param placement: where `fn` is defined
    :return: the wrapper
    """
    lock = threading.RLock()
    results: dict | weakref.WeakKeyDictionary = (weakref.WeakKeyDictionary()
                                                 if level is OneshotLevel.PER_CLASS else dict())
    running: set = set()

    def owner_of(args: tuple) -> Any:
        # The object the result belongs to: None for GLOBAL, the class for PER_CLASS,
        # the instance for PER_INSTANCE.
        if level is OneshotLevel.GLOBAL:
            return None
        if not args:
            raise TypeError(f"{fn.__qualname__} is oneshot {level.name} but was called without self or cls")
        bound = args[0]
        if placement is FunctionPlacement.INSTANCE_LEVEL and isinstance(bound, type):
            # A plain function receiving a class: `@classmethod` was applied on top of `@oneshot`.
            raise TypeError(f"{fn.__qualname__}: apply @oneshot above @classmethod, not below it")
        if level is OneshotLevel.PER_CLASS and placement is FunctionPlacement.INSTANCE_LEVEL:
            return type(bound)
        return bound

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        owner = owner_of(args)
        key = id(owner) if level is OneshotLevel.PER_INSTANCE else owner
        with lock:
            if key in results:
                return results[key]
            if key in running:
                raise RuntimeError(f"{fn.__qualname__} was called again while its oneshot call was still running")
            if level is OneshotLevel.PER_INSTANCE:
                try:
                    weakref.ref(owner)
                except TypeError:
                    raise TypeError(f"{fn.__qualname__} is oneshot PER_INSTANCE, but "
                                    f"{type(owner).__name__} instances don't support weak references") from None
            running.add(key)
            try:
                result = fn(*args, **kwargs)
            finally:
                running.discard(key)
            if level is OneshotLevel.PER_INSTANCE:
                # Drops the result before the instance's id can be reused; runs without the lock,
                # dict.pop is atomic on its own.
                weakref.finalize(owner, results.pop, key, None)
            results[key] = result
            return result

    return wrapper