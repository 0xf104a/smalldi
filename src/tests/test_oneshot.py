"""
Specification of `oneshot` and `OneshotLevel` from `smalldi.decorator`.

A oneshot function runs once per key and every later call returns the first
result: once everywhere for `GLOBAL`, once per class for `PER_CLASS`, once per
instance for `PER_INSTANCE`. A call that raises stores nothing, a re-entrant
call raises `RuntimeError`, and concurrent first calls run the function once.
"""
import dataclasses
import threading
import time
import warnings
import weakref

import pytest

from smalldi.decorator import oneshot, OneshotLevel


def module_level():
    return object()


# ---------------------------------------------------------------------------
# GLOBAL: the bare form and @oneshot()
# ---------------------------------------------------------------------------

def test_bare_oneshot_runs_once_and_keeps_the_first_result():
    calls = []

    @oneshot
    def compute(x):
        calls.append(x)
        return object()

    first = compute(1)
    assert compute(2) is first
    assert compute(3) is first
    assert calls == [1]


def test_oneshot_with_parentheses_is_global():
    calls = []

    @oneshot()
    def compute(x):
        calls.append(x)
        return object()

    first = compute(1)
    assert compute(2) is first
    assert calls == [1]


def test_oneshot_keeps_name_and_doc():
    @oneshot
    def documented():
        """Runs once."""

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "Runs once."


def test_oneshot_above_staticmethod_runs_once_on_class_and_instance():
    calls = []

    class Pantry:
        @oneshot
        @staticmethod
        def stock():
            calls.append(1)
            return object()

    first = Pantry.stock()
    assert Pantry().stock() is first
    assert Pantry.stock() is first
    assert calls == [1]


# ---------------------------------------------------------------------------
# PER_CLASS
# ---------------------------------------------------------------------------

def test_per_class_classmethod_runs_once_per_class():
    calls = []

    class Base:
        @oneshot(OneshotLevel.PER_CLASS)
        @classmethod
        def make(cls):
            calls.append(cls)
            return object()

    class Sub(Base):
        pass

    base = Base.make()
    assert Base.make() is base
    sub = Sub.make()
    assert sub is not base
    assert Sub.make() is sub
    assert Base().make() is base
    assert Sub().make() is sub
    assert calls == [Base, Sub]


def test_per_class_instance_method_runs_once_per_type():
    calls = []

    class Cat:
        @oneshot(OneshotLevel.PER_CLASS)
        def nap_spot(self):
            calls.append(type(self))
            return object()

    class Kitten(Cat):
        pass

    first, second = Cat(), Cat()
    spot = first.nap_spot()
    assert second.nap_spot() is spot
    kitten_spot = Kitten().nap_spot()
    assert kitten_spot is not spot
    assert Kitten().nap_spot() is kitten_spot
    assert calls == [Cat, Kitten]


# ---------------------------------------------------------------------------
# PER_INSTANCE
# ---------------------------------------------------------------------------

def test_per_instance_runs_once_per_instance():
    calls = []

    class Cat:
        @oneshot(OneshotLevel.PER_INSTANCE)
        def bowl(self):
            calls.append(self)
            return object()

    first, second = Cat(), Cat()
    bowl = first.bowl()
    assert first.bowl() is bowl
    assert second.bowl() is not bowl
    assert second.bowl() is second.bowl()
    assert calls == [first, second]


def test_per_instance_works_on_unhashable_instance():
    @dataclasses.dataclass
    class Cat:
        name: str

        @oneshot(OneshotLevel.PER_INSTANCE)
        def bowl(self):
            return object()

    cat = Cat("Pusheen")
    with pytest.raises(TypeError):
        hash(cat)
    assert cat.bowl() is cat.bowl()
    assert Cat("Pusheen").bowl() is not cat.bowl()


def test_per_instance_requires_weak_references():
    class Rock:
        __slots__ = ()

        @oneshot(OneshotLevel.PER_INSTANCE)
        def weight(self):
            return 1

    rock = Rock()
    try:
        weakref.ref(rock)
    except TypeError:
        with pytest.raises(TypeError):
            rock.weight()
    else:
        # GraalPy gives every object weak references, __slots__ or not
        assert rock.weight() == 1


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

def test_per_instance_outside_instance_method_is_refused_at_decoration():
    with pytest.raises(TypeError):
        class OnClassmethod:
            @oneshot(OneshotLevel.PER_INSTANCE)
            @classmethod
            def make(cls):
                return 1

    with pytest.raises(TypeError):
        class OnStaticmethod:
            @oneshot(OneshotLevel.PER_INSTANCE)
            @staticmethod
            def make():
                return 1

    with pytest.raises(TypeError):
        oneshot(OneshotLevel.PER_INSTANCE)(module_level)


def test_per_class_outside_method_is_refused_at_decoration():
    with pytest.raises(TypeError):
        class OnStaticmethod:
            @oneshot(OneshotLevel.PER_CLASS)
            @staticmethod
            def make():
                return 1

    with pytest.raises(TypeError):
        oneshot(OneshotLevel.PER_CLASS)(module_level)


def test_classmethod_above_oneshot_per_class_is_refused_on_call():
    class Wrong:
        @classmethod
        @oneshot(OneshotLevel.PER_CLASS)
        def make(cls):
            return 1

    with pytest.raises(TypeError):
        Wrong.make()


# ---------------------------------------------------------------------------
# Failures and re-entrance
# ---------------------------------------------------------------------------

def test_exception_is_not_cached():
    calls = []

    @oneshot
    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("boom")
        return object()

    with pytest.raises(ValueError):
        flaky()
    first = flaky()
    assert flaky() is first
    assert calls == [1, 1]


def test_reentrant_call_raises_runtime_error():
    calls = []
    reenter = [True]

    @oneshot
    def guarded():
        calls.append(1)
        if reenter[0]:
            reenter[0] = False
            return guarded()
        return object()

    with pytest.raises(RuntimeError):
        guarded()
    assert calls == [1]
    first = guarded()
    assert guarded() is first
    assert calls == [1, 1]


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------

def _run_threads(workers, timeout=5.0):
    threads = [threading.Thread(target=worker) for worker in workers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=timeout)
    assert not any(thread.is_alive() for thread in threads), "a thread is still alive"


def test_concurrent_first_calls_run_the_function_once():
    calls = []

    @oneshot
    def slow():
        calls.append(1)
        time.sleep(0.05)
        return object()

    count = 16
    barrier = threading.Barrier(count)
    results = []
    lock = threading.Lock()

    def worker():
        barrier.wait()
        result = slow()
        with lock:
            results.append(result)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _run_threads([worker] * count)
    assert calls == [1]
    assert len(results) == count
    assert all(result is results[0] for result in results)


def test_concurrent_first_calls_per_class_run_once_per_class():
    calls = []

    class Base:
        @oneshot(OneshotLevel.PER_CLASS)
        @classmethod
        def make(cls):
            calls.append(cls)
            time.sleep(0.05)
            return object()

    class Sub(Base):
        pass

    count = 16
    barrier = threading.Barrier(count)
    results = {Base: [], Sub: []}
    lock = threading.Lock()

    def worker_for(target):
        def worker():
            barrier.wait()
            result = target.make()
            with lock:
                results[target].append(result)
        return worker

    _run_threads([worker_for(Base if i % 2 == 0 else Sub) for i in range(count)])
    assert sorted(calls, key=lambda c: c.__name__) == [Base, Sub]
    for target, seen in results.items():
        assert len(seen) == count // 2
        assert all(result is seen[0] for result in seen)
    assert results[Base][0] is not results[Sub][0]
