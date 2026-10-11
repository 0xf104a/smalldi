"""
`InjectionContextRegistry`, which tells `Injector` the current context of the running execution slice.

An execution slice is the running `asyncio.Task` when code runs inside a
Task, otherwise the current `threading.Thread` object. Contexts are tracked
per slice: a slice with nothing pushed sees the root context, a new thread or
Task starts with nothing pushed whatever its creator had pushed, and a slice
that finishes with contexts still open has them removed with a
`ResourceWarning`.
"""
import asyncio
import threading
import warnings
import weakref
from typing import Callable

from smalldi._context.tree import ContextTree
from smalldi.context import InjectionContext

ExecutionSlice = asyncio.Task | threading.Thread

_thread_local = threading.local()


class _ThreadDeathSentinel:
    """
    Thread-local object whose finalizer runs when its thread's local storage is torn down.
    """
    pass


def _current_slice() -> ExecutionSlice:
    """
    Returns the running execution slice.

    :return: the running `asyncio.Task` if there is one, else the current `threading.Thread`
    """
    try:
        task = asyncio.current_task()
    except RuntimeError:  # no running event loop in this thread
        task = None
    return task if task is not None else threading.current_thread()


def _on_slice_death(slice_obj: ExecutionSlice, callback: Callable[[ExecutionSlice], None]) -> None:
    """
    Arranges for `callback(slice_obj)` to run once the slice has finished.

    A Task gets a done callback. A thread gets a `weakref.finalize` on a
    sentinel kept in its thread-local storage, which is collected when the
    thread ends; the thread's own locals are reachable only from inside it.

    :param slice_obj: the slice to watch
    :param callback: called with the slice once it has finished
    :raises RuntimeError: if `slice_obj` is a thread other than the calling one
    """
    if isinstance(slice_obj, asyncio.Task):
        slice_obj.add_done_callback(callback)
        return
    if slice_obj is not threading.current_thread():
        raise RuntimeError("Thread death can only be watched from inside that thread")
    sentinel = getattr(_thread_local, "death_sentinel", None)
    if sentinel is None:
        sentinel = _thread_local.death_sentinel = _ThreadDeathSentinel()
    weakref.finalize(sentinel, callback, slice_obj)


class InjectionContextRegistry:
    """
    The root context and the per-slice context stacks, as seen by `Injector`.

    `current_context` resolves the running execution slice and returns the
    context on top of its stack, or the root context. `push_context` and
    `pop_context` are called by `InjectionContextManager` under the injector's
    class mutex; the first push on a slice also watches the slice, so that
    contexts it leaves open when it finishes are popped with a
    `ResourceWarning`.

    `Injector` owns one registry, created with an empty root context, at class
    level.
    """
    def __init__(self):
        """
        Creates a registry with an empty root context and no watched slice.
        """
        self._tree = ContextTree(InjectionContext())
        self._watched: set[ExecutionSlice] = set()
        self._watched_mutex = threading.Lock()

    @staticmethod
    def _slice() -> ExecutionSlice:
        """
        :return: the running execution slice, see `_current_slice`
        """
        return _current_slice()

    @property
    def current_context(self) -> InjectionContext:
        """
        The context on top of the running slice's stack, or the root context if nothing is pushed.
        """
        return self._tree.current_context_for(self._slice())

    def push_context(self, context: InjectionContext) -> object:
        """
        Makes `context` the current context of the running slice and watches the slice.

        :param context: the context to push
        :return: a token identifying the push, to be passed to `pop_context`
        """
        slice_obj = self._slice()
        self._watch(slice_obj)
        return self._tree.add_context_for(slice_obj, context)

    def pop_context(self, token: object):
        """
        Undoes the push that returned `token`, if it is the running slice's innermost one.

        :param token: the token returned by `push_context`
        :raises RuntimeError: if the push is not the slice's innermost one; the stack is left unchanged
        """
        self._tree.finish_context_for(self._slice(), token)

    def _watch(self, slice_obj: ExecutionSlice):
        """
        Registers `_on_death` to run when the slice finishes, once per slice.

        :param slice_obj: the running slice
        """
        with self._watched_mutex:
            if slice_obj in self._watched:
                return
            self._watched.add(slice_obj)
        _on_slice_death(slice_obj, self._on_death)

    def _on_death(self, slice_obj: ExecutionSlice):
        """
        Pops every context the finished slice left open and warns if there was any.

        :param slice_obj: the finished slice
        """
        with self._watched_mutex:
            self._watched.discard(slice_obj)
        leaked = 0
        while (node := self._tree._context_slice.get(slice_obj)) is not None:
            self._tree.finish_context_for(slice_obj, node)
            leaked += 1
        if leaked:
            warnings.warn(
                f"{slice_obj!r} finished with {leaked} injection context(s) still open; "
                f"close contexts with `with`",
                ResourceWarning,
                stacklevel=1,
            )
