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
    pass


def _current_slice() -> ExecutionSlice:
    try:
        task = asyncio.current_task()
    except RuntimeError:  # no running event loop in this thread
        task = None
    return task if task is not None else threading.current_thread()


def _on_slice_death(slice_obj: ExecutionSlice, callback: Callable[[ExecutionSlice], None]) -> None:
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
    def __init__(self):
        self._tree = ContextTree(InjectionContext())
        self._watched: set[ExecutionSlice] = set()
        self._watched_mutex = threading.Lock()

    @staticmethod
    def _slice() -> ExecutionSlice:
        return _current_slice()

    @property
    def current_context(self) -> InjectionContext:
        return self._tree.get_current_node_for_id(self._slice())

    def push_context(self, context: InjectionContext) -> object:
        slice_obj = self._slice()
        self._watch(slice_obj)
        return self._tree.add_context_for(slice_obj, context)

    def pop_context(self, token: object):
        self._tree.finish_context_for(self._slice(), token)

    def _watch(self, slice_obj: ExecutionSlice):
        with self._watched_mutex:
            if slice_obj in self._watched:
                return
            self._watched.add(slice_obj)
        _on_slice_death(slice_obj, self._on_death)

    def _on_death(self, slice_obj: ExecutionSlice):
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