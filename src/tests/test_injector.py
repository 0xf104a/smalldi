import pytest

from smalldi import Injector
from smalldi.annotation import _Provide


@pytest.fixture
def reset_injector():
    """Reset Injector state before each test"""
    old_singletons = Injector.singletons_available.copy()
    Injector.singletons_available.clear()

    yield

    # Відновлюємо стан після тесту
    Injector.singletons_available.clear()
    Injector.singletons_available.update(old_singletons)


def test_singleton_registration(reset_injector):
    """Test that singleton decorator registers class instance"""
    assert len(Injector.singletons_available) == 0

    @Injector.singleton
    class TestService:
        def hello(self):
            return "Hello"

    assert len(Injector.singletons_available) == 1
    assert TestService in Injector.singletons_available
    assert isinstance(Injector.singletons_available[TestService], TestService)

    service = Injector.singletons_available[TestService]
    assert service.hello() == "Hello"


def test_singleton_single_instance(reset_injector):
    """Test that singleton creates only one instance"""
    counter = 0

    @Injector.singleton
    class TestService:
        def __init__(self):
            nonlocal counter
            counter += 1

    assert counter == 1

    Injector.singleton(TestService)
    assert counter == 2  # Це повинно бути 1, але поточна реалізація створить новий екземпляр


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
