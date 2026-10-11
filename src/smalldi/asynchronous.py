"""
Injection into coroutine functions, used by `Injector.inject`.

`@Injector.inject` on an `async def` function returns a coroutine function
built here. Its `Provide[T]` parameters are resolved when the coroutine
starts running, not when the function is called, so the instances come from
the injection context current at that moment.
"""
import functools
import inspect
from typing import Any, Callable


def is_coroutine_function(fn: Callable) -> bool:
    """
    Tells whether a function must be wrapped by `wrap_coroutine_function`.

    :param fn: function to check
    :return: True if `fn` is an `async def` function
    """
    return inspect.iscoroutinefunction(fn)


def wrap_coroutine_function(fn: Callable, name2type: dict[str, type],
                            resolve: Callable[[type], Any]) -> Callable:
    """
    Wraps a coroutine function so that its injected parameters are resolved when the coroutine runs.

    The wrapper is itself a coroutine function with the signature of `fn`.
    When the coroutine it returns starts running, every parameter in
    `name2type` that the caller didn't pass by keyword is filled with
    `resolve(type)`, then `fn` is awaited with the completed arguments.

    :param fn: `async def` function to wrap
    :param name2type: injected parameter names mapped to the registered class or interface to resolve
    :param resolve: called with each type to obtain the instance, `Injector.get_instance`
    :return: coroutine function wrapping `fn`
    :raises Exception: when the coroutine runs, whatever `resolve` or `fn` raises propagates unchanged
    """
    @functools.wraps(fn)
    async def wrapped_fn(*args, **kwargs):
        for argname, tp in name2type.items():
            if argname not in kwargs:
                kwargs[argname] = resolve(tp)
        return await fn(*args, **kwargs)
    return wrapped_fn
