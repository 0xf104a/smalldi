import pytest

from smalldi import Injector
from smalldi._singleton import SingletonFrozenError
from smalldi.annotation import _Provide


def test_singleton_registration(reset_injector):
    """Test that singleton decorator registers class instance"""
    assert len(Injector.singletons) == 0

    @Injector.singleton
    class TestService:
        def hello(self):
            return "Hello"

    assert len(Injector.singletons) == 1
    assert TestService in Injector.singletons
    assert isinstance(Injector.singletons[TestService], TestService)

    service = Injector.singletons[TestService]
    assert service.hello() == "Hello"


def test_singletons_view_is_read_only(reset_injector):
    @Injector.singleton
    class TestService:
        pass

    with pytest.raises(TypeError):
        Injector.singletons[TestService] = object()


def test_singletons_view_freezes_all(reset_injector):
    @Injector.singleton
    class TestService:
        pass

    class Override(TestService):
        pass

    Injector.singletons
    lazy = Injector._singletons_available[TestService]
    assert lazy.frozen
    with pytest.raises(SingletonFrozenError):
        lazy.override(Override)


def test_singletons_available_deprecated(reset_injector):
    @Injector.singleton
    class TestService:
        pass

    with pytest.warns(DeprecationWarning):
        view = Injector.singletons_available
    assert isinstance(view[TestService], TestService)


def test_singleton_single_instance(reset_injector):
    """Test that singleton is created lazily and only once"""
    counter = 0

    @Injector.singleton
    class TestService:
        def __init__(self):
            nonlocal counter
            counter += 1

    assert counter == 0

    first = Injector.singletons[TestService]
    assert Injector.singletons[TestService] is first
    assert counter == 1


def test_singleton_reregistration_warns(reset_injector):
    @Injector.singleton
    class TestService:
        pass

    with pytest.warns(RuntimeWarning):
        Injector.singleton(TestService)
    assert len(Injector.singletons) == 1


def test_singleton_reload_warns(reset_injector):
    def make():
        class TestService:
            pass
        return TestService

    Injector.singleton(make())
    with pytest.warns(RuntimeWarning):
        Injector.singleton(make())


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


def test_inject_missing_singleton_raises_at_decoration(reset_injector):
    class NotRegistered:
        pass

    with pytest.raises(TypeError):
        @Injector.inject
        def test_function(service: _Provide[NotRegistered]):
            pass


def test_inject_is_lazy(reset_injector):
    """Decorating doesn't create the singleton, the first call does"""
    counter = 0

    @Injector.singleton
    class TestService:
        def __init__(self):
            nonlocal counter
            counter += 1

    @Injector.inject
    def test_function(service: _Provide[TestService]):
        return service

    assert counter == 0
    first = test_function()
    assert test_function() is first
    assert counter == 1


def test_inject_explicit_kwarg_wins(reset_injector):
    @Injector.singleton
    class TestService:
        pass

    @Injector.inject
    def test_function(service: _Provide[TestService]):
        return service

    sentinel = object()
    assert test_function(service=sentinel) is sentinel
    # The singleton was never needed, so it wasn't created
    assert not Injector._singletons_available[TestService].frozen


def test_inject_keeps_other_arguments(reset_injector):
    @Injector.singleton
    class TestService:
        pass

    @Injector.inject
    def test_function(a, service: _Provide[TestService], b=2):
        return a, b, service

    a, b, service = test_function(1, b=3)
    assert (a, b) == (1, 3)
    assert isinstance(service, TestService)


def test_inject_override_before_first_call(reset_injector):
    @Injector.singleton
    class TestService:
        pass

    class Override(TestService):
        pass

    @Injector.inject
    def test_function(service: _Provide[TestService]):
        return service

    Injector._singletons_available[TestService].override(Override)
    assert type(test_function()) is Override


def test_singleton_rejects_abstract(reset_injector):
    from abc import ABC, abstractmethod

    class Abstract(ABC):
        @abstractmethod
        def run(self):
            pass

    with pytest.raises(TypeError):
        Injector.singleton(Abstract)
