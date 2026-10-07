import threading
import warnings

import pytest
from typing import Any, Dict

from smalldi import Injector
from smalldi._interfaces import InterfaceResolver

# How long a test waits for the injector lock before concluding that a thread of an
# earlier test deadlocked while holding it
_LOCK_TIMEOUT = 2.0


def _ensure_injector_unlocked():
    """
    Gives the injector a fresh lock if its current one is held by a thread that will never release it.

    A concurrency test whose threads deadlock fails, but its daemon threads stay blocked
    and may keep the injector's class mutex forever. Without this guard every later test
    that registers or resolves anything would hang instead of running.
    """
    lock = Injector.__class_mutex__
    if lock.acquire(timeout=_LOCK_TIMEOUT):
        lock.release()
        return
    warnings.warn(
        "the injector lock is held by a deadlocked thread of an earlier test; replacing it",
        RuntimeWarning,
    )
    Injector.__class_mutex__ = threading.RLock()


@pytest.fixture(autouse=False)
def reset_injector():
    """Reset Injector state before and after each test"""
    _ensure_injector_unlocked()
    old_singletons: Dict[Any, Any] = Injector._singletons_available.copy()
    old_resolver = Injector._interface_resolver

    Injector._singletons_available.clear()
    Injector._interface_resolver = InterfaceResolver()

    yield

    Injector._singletons_available.clear()
    Injector._singletons_available.update(old_singletons)
    Injector._interface_resolver = old_resolver
