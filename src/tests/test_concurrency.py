import threading

import pytest

from smalldi.concurrency import synchronized, threadsafe

# Long enough for a thread that isn't blocked to make progress
_BLOCK_TIMEOUT = 0.1


def _assert_blocks(hold, call):
    """
    Runs `hold` in a thread until it signals it's inside the guarded section,
    then checks that `call` from another thread can't enter until `hold` leaves.
    """
    inside = threading.Event()
    release = threading.Event()
    entered = threading.Event()

    holder = threading.Thread(target=hold, args=(inside, release))
    holder.start()
    assert inside.wait(1)

    caller = threading.Thread(target=lambda: (call(), entered.set()))
    caller.start()
    assert not entered.wait(_BLOCK_TIMEOUT)

    release.set()
    holder.join(1)
    caller.join(1)
    assert entered.is_set()


def _assert_not_blocks(hold, call):
    inside = threading.Event()
    release = threading.Event()

    holder = threading.Thread(target=hold, args=(inside, release))
    holder.start()
    assert inside.wait(1)
    try:
        caller = threading.Thread(target=call)
        caller.start()
        caller.join(1)
        assert not caller.is_alive()
    finally:
        release.set()
        holder.join(1)


def test_synchronized_returns_result_and_keeps_metadata():
    @synchronized
    def add(a, b):
        """Adds numbers"""
        return a + b

    assert add(1, b=2) == 3
    assert add.__name__ == "add"
    assert add.__doc__ == "Adds numbers"


def test_synchronized_is_mutually_exclusive():
    @synchronized
    def guarded(inside=None, release=None):
        if inside is not None:
            inside.set()
            release.wait(1)

    _assert_blocks(guarded, guarded)


def test_synchronized_is_reentrant():
    @synchronized
    def countdown(n):
        return 0 if n == 0 else countdown(n - 1) + 1

    assert countdown(3) == 3


def test_threadsafe_instance_method_locks_per_instance():
    class Service:
        @threadsafe
        def work(self, inside=None, release=None):
            if inside is not None:
                inside.set()
                release.wait(1)
            return self

    a, b = Service(), Service()
    assert a.work() is a
    _assert_blocks(a.work, a.work)
    _assert_not_blocks(a.work, b.work)


def test_threadsafe_classmethod_locks_per_class():
    class Base:
        @threadsafe
        @classmethod
        def work(cls, inside=None, release=None):
            if inside is not None:
                inside.set()
                release.wait(1)
            return cls

    class Child(Base):
        pass

    assert Base.work() is Base
    assert Child.work() is Child
    _assert_blocks(Base.work, Base.work)
    # A subclass doesn't share its parent's lock
    _assert_not_blocks(Base.work, Child.work)


def test_threadsafe_staticmethod():
    class Service:
        @threadsafe
        @staticmethod
        def work(inside=None, release=None):
            if inside is not None:
                inside.set()
                release.wait(1)
            return "static"

    assert Service.work() == "static"
    assert Service().work() == "static"
    _assert_blocks(Service.work, Service.work)


def test_threadsafe_outside_class_warns_and_synchronizes():
    with pytest.warns(UserWarning, match="synchronized"):
        @threadsafe
        def fn(inside=None, release=None):
            if inside is not None:
                inside.set()
                release.wait(1)
            return 1

    assert fn() == 1
    _assert_blocks(fn, fn)


def test_threadsafe_requires_mutex_slot():
    class Slotted:
        __slots__ = ()

        @threadsafe
        def work(self):
            pass

    class SlottedWithMutex:
        __slots__ = ("__instance_mutex__",)

        @threadsafe
        def work(self):
            return "ok"

    with pytest.raises(TypeError, match="__instance_mutex__"):
        Slotted().work()
    assert SlottedWithMutex().work() == "ok"


def test_threadsafe_bypasses_custom_setattr():
    class Frozen:
        def __setattr__(self, name, value):
            raise AttributeError("frozen")

        @threadsafe
        def work(self):
            return "ok"

    assert Frozen().work() == "ok"


def test_synchronized_rejects_async():
    async def coroutine_fn():
        pass

    async def async_gen_fn():
        yield

    with pytest.raises(NotImplementedError):
        synchronized(coroutine_fn)
    with pytest.raises(NotImplementedError):
        synchronized(async_gen_fn)


@pytest.mark.parametrize("wrap", [lambda f: f, staticmethod, classmethod])
def test_threadsafe_rejects_async(wrap):
    async def coroutine_fn(*args):
        pass

    async def async_gen_fn(*args):
        yield

    with pytest.raises(NotImplementedError):
        threadsafe(wrap(coroutine_fn))
    with pytest.raises(NotImplementedError):
        threadsafe(wrap(async_gen_fn))
