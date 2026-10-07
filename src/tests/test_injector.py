from abc import ABC, abstractmethod

import pytest

from smalldi import Injector, Provide, SingletonFrozenError


def test_singleton_registration(reset_injector):
    """The singleton decorator registers the class and returns it unchanged"""
    class Plain:
        pass

    assert not Injector.is_singleton(Plain)

    @Injector.singleton
    class TestService:
        def hello(self):
            return "Hello"

    assert Injector.is_singleton(TestService)
    assert not Injector.is_interface(TestService)
    service = Injector.get_instance(TestService)
    assert isinstance(service, TestService)
    assert service.hello() == "Hello"


def test_singletons_available_is_read_only(reset_injector):
    """The deprecated snapshot can't be written to"""
    @Injector.singleton
    class TestService:
        pass

    with pytest.warns(DeprecationWarning):
        view = Injector.singletons_available
    with pytest.raises(TypeError):
        view[TestService] = object()


def test_singletons_available_freezes_all_singletons(reset_injector):
    """Reading the deprecated snapshot instantiates and freezes every registered singleton"""
    created = []

    @Injector.singleton
    class TestService:
        def __init__(self):
            created.append(type(self))

    @Injector.singleton
    class Override(TestService):
        pass

    with pytest.warns(DeprecationWarning):
        view = Injector.singletons_available

    assert created == [TestService, Override]
    assert view[TestService] is Injector.get_instance(TestService)
    with pytest.raises(SingletonFrozenError):
        Injector.override(TestService)(Override)


def test_singletons_available_deprecated(reset_injector):
    """Every read warns and maps each registered class to its instance; overridden classes map to the override"""
    @Injector.singleton
    class TestService:
        pass

    @Injector.override(TestService)
    @Injector.singleton
    class FakeService(TestService):
        pass

    with pytest.warns(DeprecationWarning, match="1.0.0"):
        view = Injector.singletons_available
    with pytest.warns(DeprecationWarning):
        Injector.singletons_available

    assert set(view) == {TestService, FakeService}
    assert type(view[TestService]) is FakeService
    assert view[TestService] is view[FakeService]
    assert view[FakeService] is Injector.get_instance(FakeService)


def test_singletons_available_excludes_interfaces(reset_injector):
    """Interfaces aren't part of the deprecated snapshot, their implementations are"""
    @Injector.interface
    class Mailer(ABC):
        @abstractmethod
        def send(self):
            pass

    @Injector.implements(Mailer)
    @Injector.singleton
    class MailService(Mailer):
        def send(self):
            return "sent"

    with pytest.warns(DeprecationWarning):
        view = Injector.singletons_available

    assert set(view) == {MailService}


def test_singleton_single_instance(reset_injector):
    """A singleton is created lazily and only once"""
    counter = 0

    @Injector.singleton
    class TestService:
        def __init__(self):
            nonlocal counter
            counter += 1

    assert counter == 0

    first = Injector.get_instance(TestService)
    assert Injector.get_instance(TestService) is first
    assert counter == 1


def test_singleton_reregistration_raises(reset_injector):
    """Registering the same class twice raises TypeError and keeps the first registration"""
    @Injector.singleton
    class TestService:
        pass

    with pytest.raises(TypeError, match="already"):
        Injector.singleton(TestService)
    assert Injector.is_singleton(TestService)
    assert isinstance(Injector.get_instance(TestService), TestService)


def test_inject_basic(reset_injector):
    """Basic dependency injection"""
    @Injector.singleton
    class TestService:
        def hello(self):
            return "Hello"

    @Injector.inject
    def test_function(service: Provide[TestService]):
        return service.hello()

    result = test_function()
    assert result == "Hello"


def test_inject_multiple_dependencies(reset_injector):
    """Injection of several dependencies into one function"""
    @Injector.singleton
    class ServiceA:
        def value(self):
            return "A"

    @Injector.singleton
    class ServiceB:
        def value(self):
            return "B"

    @Injector.inject
    def test_function(service_a: Provide[ServiceA], service_b: Provide[ServiceB]):
        return service_a.value() + service_b.value()

    result = test_function()
    assert result == "AB"


def test_inject_missing_singleton_raises_at_decoration(reset_injector):
    class NotRegistered:
        pass

    with pytest.raises(TypeError):
        @Injector.inject
        def test_function(service: Provide[NotRegistered]):
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
    def test_function(service: Provide[TestService]):
        return service

    assert counter == 0
    first = test_function()
    assert test_function() is first
    assert counter == 1


def test_inject_explicit_kwarg_wins(reset_injector):
    """An argument passed by keyword replaces the injected one, and the singleton isn't created"""
    created = []

    @Injector.singleton
    class TestService:
        def __init__(self):
            created.append(self)

    @Injector.singleton
    class FakeService(TestService):
        pass

    @Injector.inject
    def test_function(service: Provide[TestService]):
        return service

    sentinel = object()
    assert test_function(service=sentinel) is sentinel
    assert created == []
    # The singleton was never needed, so it isn't frozen and can still be overridden
    Injector.override(TestService)(FakeService)
    assert type(test_function()) is FakeService


def test_inject_positional_dependency_raises(reset_injector):
    """Dependencies can't be passed positionally: the parameter is filled by keyword as well"""
    @Injector.singleton
    class TestService:
        pass

    @Injector.inject
    def test_function(service: Provide[TestService]):
        return service

    with pytest.raises(TypeError):
        test_function(object())


def test_inject_keeps_other_arguments(reset_injector):
    @Injector.singleton
    class TestService:
        pass

    @Injector.inject
    def test_function(a, service: Provide[TestService], b=2):
        return a, b, service

    a, b, service = test_function(1, b=3)
    assert (a, b) == (1, 3)
    assert isinstance(service, TestService)


def test_inject_override_before_first_call(reset_injector):
    @Injector.singleton
    class TestService:
        pass

    @Injector.inject
    def test_function(service: Provide[TestService]):
        return service

    @Injector.override(TestService)
    @Injector.singleton
    class Override(TestService):
        pass

    assert type(test_function()) is Override


def test_singleton_rejects_abstract(reset_injector):
    class Abstract(ABC):
        @abstractmethod
        def run(self):
            pass

    with pytest.raises(TypeError):
        Injector.singleton(Abstract)


def test_interface_rejects_concrete_class(reset_injector):
    class Concrete:
        def run(self):
            pass

    with pytest.raises(TypeError):
        Injector.interface(Concrete)


def test_interface_reregistration_raises(reset_injector):
    @Injector.interface
    class Mailer(ABC):
        @abstractmethod
        def send(self):
            pass

    with pytest.raises(TypeError):
        Injector.interface(Mailer)
    assert Injector.is_interface(Mailer)


def test_resolving_unregistered_class_raises_key_error(reset_injector):
    class NotRegistered:
        pass

    with pytest.raises(KeyError):
        Injector.get_instance(NotRegistered)


def test_override_singleton(reset_injector):
    @Injector.singleton
    class MailService:
        def send(self):
            return "sent"

    @Injector.override(MailService)
    @Injector.singleton
    class FakeMailService(MailService):
        def send(self):
            return "faked"

    @Injector.inject
    def fn(mail: Provide[MailService], fake: Provide[FakeMailService]):
        return mail, fake

    mail, fake = fn()
    assert mail.send() == "faked"
    # Same instance as injecting the override directly
    assert mail is fake


def test_override_singleton_requires_subclass(reset_injector):
    @Injector.singleton
    class MailService:
        pass

    with pytest.raises(TypeError, match="not a subclass"):
        @Injector.override(MailService)
        @Injector.singleton
        class Unrelated:
            pass


def test_override_singleton_with_itself_is_rejected(reset_injector):
    @Injector.singleton
    class MailService:
        pass

    with pytest.raises(TypeError, match="itself"):
        Injector.override(MailService)(MailService)


def test_override_singleton_requires_override_to_be_singleton(reset_injector):
    @Injector.singleton
    class MailService:
        pass

    with pytest.raises(TypeError, match="above @Injector.singleton"):
        @Injector.override(MailService)
        class FakeMailService(MailService):
            pass


def test_override_interface_and_singleton_at_once(reset_injector):
    """One singleton may override an interface and a singleton with stacked decorators"""
    @Injector.interface
    class Mailer(ABC):
        @abstractmethod
        def send(self):
            pass

    @Injector.singleton
    class MailService(Mailer):
        def send(self):
            return "sent"

    @Injector.override(Mailer)
    @Injector.override(MailService)
    @Injector.singleton
    class FakeMailService(MailService):
        pass

    fake = Injector.get_instance(FakeMailService)
    assert Injector.get_instance(Mailer) is fake
    assert Injector.get_instance(MailService) is fake
