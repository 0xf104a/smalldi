import pytest

from smalldi import Injector
from smalldi._singleton import LazySingleton, SingletonFrozenError
from smalldi.annotation import _Provide


def test_singleton_registration(reset_injector):
    """Test that singleton decorator registers class instance"""
    assert len(Injector._singletons) == 0

    @Injector.singleton
    class TestService:
        def hello(self):
            return "Hello"

    assert len(Injector._singletons) == 1
    assert TestService in Injector._singletons
    assert isinstance(Injector._singletons[TestService], TestService)

    service = Injector._singletons[TestService]
    assert service.hello() == "Hello"


def test_singletons_view_is_read_only(reset_injector):
    @Injector.singleton
    class TestService:
        pass

    with pytest.raises(TypeError):
        Injector._singletons[TestService] = object()


def test_singletons_view_freezes_all(reset_injector):
    @Injector.singleton
    class TestService:
        pass

    class Override(TestService):
        pass

    Injector._singletons
    lazy = Injector._singletons_available[TestService]
    assert lazy.frozen
    with pytest.raises(SingletonFrozenError):
        lazy.override(LazySingleton(Override))


def test_singletons_available_deprecated(reset_injector):
    @Injector.singleton
    class TestService:
        pass

    with pytest.warns(DeprecationWarning):
        view = Injector.singletons_available
    assert isinstance(view[TestService], TestService)
    # Reading it freezes the registry like the private snapshot does
    assert Injector._singletons_available[TestService].frozen


def test_singleton_single_instance(reset_injector):
    """Test that singleton is created lazily and only once"""
    counter = 0

    @Injector.singleton
    class TestService:
        def __init__(self):
            nonlocal counter
            counter += 1

    assert counter == 0

    first = Injector._singletons[TestService]
    assert Injector._singletons[TestService] is first
    assert counter == 1


def test_singleton_reregistration_raises(reset_injector):
    @Injector.singleton
    class TestService:
        pass

    with pytest.raises(TypeError, match="already registered"):
        Injector.singleton(TestService)
    assert len(Injector._singletons) == 1


def test_singleton_reload_raises(reset_injector):
    """A reloaded module produces a new class object with the same name"""
    def make():
        class TestService:
            pass
        return TestService

    first = Injector.singleton(make())
    with pytest.raises(TypeError, match="already registered"):
        Injector.singleton(make())
    assert set(Injector._singletons_available) == {first}


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

    @Injector.inject
    def test_function(service: _Provide[TestService]):
        return service

    @Injector.override(TestService)
    @Injector.singleton
    class Override(TestService):
        pass

    assert type(test_function()) is Override


def test_singleton_rejects_abstract(reset_injector):
    from abc import ABC, abstractmethod

    class Abstract(ABC):
        @abstractmethod
        def run(self):
            pass

    with pytest.raises(TypeError):
        Injector.singleton(Abstract)


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
    def fn(mail: _Provide[MailService], fake: _Provide[FakeMailService]):
        return mail, fake

    mail, fake = fn()
    assert mail.send() == "faked"
    # Same instance as injecting the override directly
    assert mail is fake


def test_overridden_singleton_is_never_instantiated(reset_injector):
    created = []

    @Injector.singleton
    class MailService:
        def __init__(self):
            created.append(type(self))

    @Injector.override(MailService)
    @Injector.singleton
    class FakeMailService(MailService):
        pass

    Injector._get_instance(MailService)
    singletons = Injector._singletons
    assert created == [FakeMailService]
    assert singletons[MailService] is singletons[FakeMailService]


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


def test_override_requires_registered_singleton(reset_injector):
    class NotSingleton:
        pass

    with pytest.raises(TypeError, match="neither an interface nor a singleton"):
        @Injector.override(NotSingleton)
        @Injector.singleton
        class Fake(NotSingleton):
            pass


def test_override_singleton_requires_override_to_be_singleton(reset_injector):
    @Injector.singleton
    class MailService:
        pass

    with pytest.raises(TypeError, match="above @Injector.singleton"):
        @Injector.override(MailService)
        class FakeMailService(MailService):
            pass


def test_second_singleton_override_raises(reset_injector):
    @Injector.singleton
    class MailService:
        pass

    @Injector.override(MailService)
    @Injector.singleton
    class First(MailService):
        pass

    with pytest.raises(TypeError, match="already overridden"):
        @Injector.override(MailService)
        @Injector.singleton
        class Second(MailService):
            pass

    assert isinstance(Injector._get_instance(MailService), First)


def test_singleton_override_same_class_twice_is_allowed(reset_injector):
    @Injector.singleton
    class MailService:
        pass

    @Injector.override(MailService)
    @Injector.singleton
    class FakeMailService(MailService):
        pass

    Injector.override(MailService)(FakeMailService)
    assert isinstance(Injector._get_instance(MailService), FakeMailService)


def test_override_singleton_after_injection_is_rejected(reset_injector):
    @Injector.singleton
    class MailService:
        pass

    Injector._get_instance(MailService)

    with pytest.raises(SingletonFrozenError):
        @Injector.override(MailService)
        @Injector.singleton
        class FakeMailService(MailService):
            pass

    assert type(Injector._get_instance(MailService)) is MailService


def test_override_singleton_after_reading_singletons_is_rejected(reset_injector):
    @Injector.singleton
    class MailService:
        pass

    @Injector.singleton
    class FakeMailService(MailService):
        pass

    Injector._singletons
    with pytest.raises(SingletonFrozenError):
        Injector.override(MailService)(FakeMailService)


def test_singleton_overrides_are_transitive(reset_injector):
    @Injector.singleton
    class MailService:
        pass

    @Injector.override(MailService)
    @Injector.singleton
    class FakeMailService(MailService):
        pass

    @Injector.override(FakeMailService)
    @Injector.singleton
    class FakerMailService(FakeMailService):
        pass

    instance = Injector._get_instance(MailService)
    assert type(instance) is FakerMailService
    assert Injector._get_instance(FakeMailService) is instance


def test_overridden_interface_implementation_follows_override(reset_injector):
    from abc import ABC, abstractmethod

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

    @Injector.override(MailService)
    @Injector.singleton
    class FakeMailService(MailService):
        def send(self):
            return "faked"

    assert Injector._get_instance(Mailer) is Injector._get_instance(FakeMailService)


def test_injecting_interface_freezes_its_implementation(reset_injector):
    from abc import ABC, abstractmethod

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

    Injector._get_instance(Mailer)
    with pytest.raises(SingletonFrozenError):
        @Injector.override(MailService)
        @Injector.singleton
        class FakeMailService(MailService):
            pass


def test_override_interface_and_singleton_at_once(reset_injector):
    from abc import ABC, abstractmethod

    @Injector.interface
    class Mailer(ABC):
        @abstractmethod
        def send(self):
            pass

    @Injector.singleton
    class MailService(Mailer):
        def send(self):
            return "sent"

    @Injector.override(Mailer, MailService)
    @Injector.singleton
    class FakeMailService(MailService):
        pass

    fake = Injector._get_instance(FakeMailService)
    assert Injector._get_instance(Mailer) is fake
    assert Injector._get_instance(MailService) is fake


def test_override_singleton_all_or_nothing(reset_injector):
    @Injector.singleton
    class A:
        pass

    @Injector.singleton
    class B:
        pass

    Injector._get_instance(B)

    with pytest.raises(SingletonFrozenError):
        @Injector.override(A, B)
        @Injector.singleton
        class Fake(A, B):
            pass

    assert type(Injector._get_instance(A)) is A


def test_override_while_constructor_injects_doesnt_deadlock(reset_injector):
    """A constructor holding its build lock may take the registry lock while override() holds it"""
    import threading

    entered = threading.Event()
    release = threading.Event()

    @Injector.singleton
    class Dependency:
        pass

    @Injector.singleton
    class Other:
        pass

    @Injector.singleton
    class Slow:
        def __init__(self):
            entered.set()
            release.wait(1)
            self.dependency = Injector._get_instance(Dependency)

    worker = threading.Thread(target=Injector._get_instance, args=(Slow,))
    worker.start()
    assert entered.wait(1)

    def override_other():
        @Injector.override(Other)
        @Injector.singleton
        class FakeOther(Other):
            pass

    overrider = threading.Thread(target=override_other)
    overrider.start()
    overrider.join(1)
    assert not overrider.is_alive()

    release.set()
    worker.join(1)
    assert not worker.is_alive()
