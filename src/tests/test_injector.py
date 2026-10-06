import threading

import pytest

from smalldi import Injector, Provide
from smalldi.annotation import _Provide


def test_singleton_registration(reset_injector):
    """Test that singleton decorator registers class instance"""
    assert len(Injector._singletons_available) == 0

    @Injector.singleton
    class TestService:
        def hello(self):
            return "Hello"

    assert len(Injector._singletons_available) == 1
    assert TestService in Injector._singletons_available
    service = Injector._singletons_available[TestService].get()
    assert isinstance(service, TestService)
    assert service.hello() == "Hello"


def test_singleton_single_instance(reset_injector):
    """Test that singleton creates only one instance, lazily"""
    counter = 0

    @Injector.singleton
    class TestService:
        def __init__(self):
            nonlocal counter
            counter += 1

    assert counter == 0

    @Injector.inject
    def fn(first: Provide[TestService], second: Provide[TestService]):
        return first, second

    assert counter == 0
    first, second = fn()
    assert first is second
    fn()
    assert counter == 1

    with pytest.raises(ValueError, match="already marked as singleton"):
        Injector.singleton(TestService)


def test_inject_basic(reset_injector):
    """Test basic dependency injection"""
    @Injector.singleton
    class TestService:
        def hello(self):
            return "Hello"

    @Injector.inject
    def test_function(service: _Provide[TestService]):
        return service.hello()

    result = test_function()
    assert result == "Hello"


def test_inject_multiple_dependencies(reset_injector):
    """Test injection of multiple dependencies"""
    @Injector.singleton
    class ServiceA:
        def value(self):
            return "A"

    @Injector.singleton
    class ServiceB:
        def value(self):
            return "B"

    @Injector.inject
    def test_function(service_a: _Provide[ServiceA], service_b: _Provide[ServiceB]):
        return service_a.value() + service_b.value()

    result = test_function()
    assert result == "AB"


def test_singleton_registered_after_inject(reset_injector):
    class Service:
        pass

    @Injector.inject
    def fn(service: Provide[Service]):
        return service

    # Resolution happens on call, so registration order doesn't matter
    Injector.singleton(Service)
    assert isinstance(fn(), Service)


def test_unavailable_singleton_raises_on_call(reset_injector):
    class Missing:
        pass

    @Injector.inject
    def fn(missing: Provide[Missing]):
        return missing

    with pytest.raises(TypeError, match="is not available"):
        fn()
    # Explicitly passed dependencies are not resolved
    value = Missing()
    assert fn(missing=value) is value


def test_failed_creation_does_not_freeze(reset_injector):
    attempts = 0

    @Injector.singleton
    class Flaky:
        def __init__(self):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("boom")

    @Injector.inject
    def fn(flaky: Provide[Flaky]):
        return flaky

    with pytest.raises(RuntimeError):
        fn()
    assert not Injector._singletons_available[Flaky].frozen
    assert isinstance(fn(), Flaky)


def test_circular_dependency_raises(reset_injector):
    class First:
        pass

    class Second:
        @Injector.inject
        def __init__(self, first: Provide[First]):
            pass

    @Injector.inject
    def first_init(self, second: Provide[Second]):
        pass

    First.__init__ = first_init
    Injector.singleton(First)
    Injector.singleton(Second)

    @Injector.inject
    def fn(first: Provide[First]):
        return first

    with pytest.raises(TypeError, match="Circular dependency"):
        fn()


def test_concurrent_injection_creates_single_instance(reset_injector):
    created = 0
    started = threading.Barrier(8)

    @Injector.singleton
    class Slow:
        def __init__(self):
            nonlocal created
            created += 1

    @Injector.inject
    def fn(slow: Provide[Slow]):
        return slow

    results = []

    def work():
        started.wait()
        results.append(fn())

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert created == 1
    assert all(r is results[0] for r in results)


def test_cross_thread_circular_dependency_raises(reset_injector):
    # Each constructor waits until both threads are inside a constructor (or the barrier times out),
    # then resolves the other singleton
    barrier = threading.Barrier(2)

    def sync():
        try:
            barrier.wait(timeout=0.5)
        except threading.BrokenBarrierError:
            pass

    class First:
        def __init__(self):
            sync()
            get_second()

    class Second:
        def __init__(self):
            sync()
            get_first()

    Injector.singleton(First)
    Injector.singleton(Second)

    @Injector.inject
    def get_first(first: Provide[First]):
        return first

    @Injector.inject
    def get_second(second: Provide[Second]):
        return second

    errors = []

    def work(fn):
        try:
            fn()
        except TypeError as e:
            errors.append(e)

    threads = [threading.Thread(target=work, args=(fn,), daemon=True) for fn in (get_first, get_second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert not any(t.is_alive() for t in threads), "threads deadlocked"
    assert len(errors) == 2
    assert all("Circular dependency" in str(e) for e in errors)


def test_singleton_does_not_mutate_class(reset_injector):
    @Injector.singleton
    class Service:
        pass

    @Injector.inject
    def fn(service: Provide[Service]):
        return service

    fn()
    assert "__singleton__" not in vars(Service)
