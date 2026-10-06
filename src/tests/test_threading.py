import threading
import time

from smalldi.threading import threadsafe, threadsafe_cls, threadsafe_fn


def _run_concurrently(target, n=8):
    threads = [threading.Thread(target=target) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def test_threadsafe_fn_serializes_calls():
    active = 0
    max_active = 0

    @threadsafe_fn
    def fn():
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        time.sleep(0.001)
        active -= 1

    _run_concurrently(fn)
    assert max_active == 1


def test_threadsafe_fn_is_reentrant():
    @threadsafe_fn
    def fact(n):
        return 1 if n <= 1 else n * fact(n - 1)

    assert fact(5) == 120


def test_threadsafe_fn_preserves_metadata():
    @threadsafe_fn
    def documented():
        """Docstring"""

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "Docstring"


def test_threadsafe_cls_serializes_methods():
    @threadsafe_cls
    class Counter:
        def __init__(self):
            self.value = 0

        def increment(self):
            value = self.value
            time.sleep(0.0001)
            self.value = value + 1

    counter = Counter()

    def work():
        for _ in range(20):
            counter.increment()

    _run_concurrently(work)
    assert counter.value == 8 * 20


def test_threadsafe_cls_methods_may_call_each_other():
    @threadsafe_cls
    class Service:
        def outer(self):
            return self.inner() + 1

        def inner(self):
            return 1

    assert Service().outer() == 2


def test_threadsafe_cls_lock_is_per_instance():
    @threadsafe_cls
    class Service:
        def __init__(self, event):
            self.event = event

        def wait(self):
            assert self.event.wait(timeout=5)

        def release(self):
            self.event.set()

    first = Service(threading.Event())
    second = Service(first.event)
    # first.wait holds first's lock; second.release must not be blocked by it
    waiter = threading.Thread(target=first.wait)
    waiter.start()
    second.release()
    waiter.join()


def test_threadsafe_cls_wraps_properties():
    @threadsafe_cls
    class Holder:
        def __init__(self):
            self._value = 0

        @property
        def value(self):
            """Value docstring"""
            assert getattr(self, "_threadsafe_lock")._is_owned()
            return self._value

        @value.setter
        def value(self, new):
            assert getattr(self, "_threadsafe_lock")._is_owned()
            self._value = new

    holder = Holder()
    holder.value = 3
    assert holder.value == 3
    assert Holder.value.__doc__ == "Value docstring"


def test_threadsafe_cls_keeps_static_and_class_methods():
    @threadsafe_cls
    class Service:
        @staticmethod
        def static():
            return "static"

        @classmethod
        def klass(cls):
            return cls

    assert Service.static() == "static"
    assert Service.klass() is Service


def test_threadsafe_cls_subclass_shares_single_lock():
    @threadsafe_cls
    class Base:
        def __init__(self):
            self.base_lock = getattr(self, "_threadsafe_lock")

    @threadsafe_cls
    class Child(Base):
        def __init__(self):
            self.child_lock = getattr(self, "_threadsafe_lock")
            super().__init__()

    child = Child()
    assert child.base_lock is child.child_lock


def test_threadsafe_dispatches_on_type():
    @threadsafe
    class Service:
        def method(self):
            return getattr(self, "_threadsafe_lock")._is_owned()

    @threadsafe
    def fn():
        return "fn"

    assert Service().method()
    assert fn() == "fn"
