import asyncio
import inspect
import sys
from abc import ABC, abstractmethod

import pytest

from smalldi import (
    Injector,
    Provide,
    SingletonFrozenError,
    implements,
    inject,
    interface,
    isinterface,
    issingleton,
    override,
    singleton,
)
from smalldi.context import InjectionSubcontextType

# GraalPy 25 evaluates the annotations of a function defined inside a coroutine to None when the module is
# compiled by pytest's assertion rewriter; the same code passes without rewriting and on GraalPy 24.2.
# sys.implementation.version is the GraalPy version on 25 and the Python version (3.x) on 24.2.
_graalpy_nested_annotation_bug = pytest.mark.xfail(
    sys.implementation.name == "graalpy" and sys.implementation.version >= (25,),
    reason="GraalPy 25: annotations of a def nested in a coroutine evaluate to None under pytest assertion rewriting",
    raises=TypeError,
    strict=True,
)


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
        _ = Injector.singletons_available

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


def test_inject_async_function_is_coroutine_function():
    """An injected async function is a coroutine function itself"""
    with Injector.context(InjectionSubcontextType.RESET):
        @Injector.singleton
        class Dep:
            pass

        @Injector.inject
        async def fn(dep: Provide[Dep]):
            return dep

        assert inspect.iscoroutinefunction(fn)
        assert asyncio.iscoroutinefunction(fn)


@_graalpy_nested_annotation_bug
def test_inject_async_function_resolves_when_coroutine_runs():
    """Dependencies are resolved when the coroutine runs, not when the function is called"""
    async def main():
        with Injector.context(InjectionSubcontextType.RESET):
            counter = 0

            @Injector.singleton
            class Dep:
                def __init__(self):
                    nonlocal counter
                    counter += 1

            @Injector.inject
            async def fn(dep: Provide[Dep]):
                return dep

            coroutine = fn()
            assert counter == 0
            dep = await coroutine
            assert counter == 1
            assert dep is Injector.get_instance(Dep)

    asyncio.run(main())


def test_inject_async_function_uses_explicit_keyword_argument():
    """A dependency passed by keyword is used instead of the injected one"""
    with Injector.context(InjectionSubcontextType.RESET):
        counter = 0

        @Injector.singleton
        class Dep:
            def __init__(self):
                nonlocal counter
                counter += 1

        @Injector.inject
        async def fn(dep: Provide[Dep]):
            return dep

        explicit = object()
        assert asyncio.run(fn(dep=explicit)) is explicit
        assert counter == 0


@_graalpy_nested_annotation_bug
def test_inject_async_function_passes_result_and_exception_through():
    """The coroutine's return value and exceptions reach the caller unchanged"""
    async def main():
        with Injector.context(InjectionSubcontextType.RESET):
            @Injector.singleton
            class Dep:
                pass

            result = object()
            error = ValueError("boom")

            @Injector.inject
            async def returns(dep: Provide[Dep]):
                return result

            @Injector.inject
            async def raises(dep: Provide[Dep]):
                raise error

            assert await returns() is result
            with pytest.raises(ValueError) as exc_info:
                await raises()
            assert exc_info.value is error

    asyncio.run(main())


def test_inject_async_function_rejects_unregistered_class():
    """Decorating an async function with an unregistered dependency raises TypeError"""
    with Injector.context(InjectionSubcontextType.RESET):
        class NotRegistered:
            pass

        with pytest.raises(TypeError):
            @Injector.inject
            async def fn(dep: Provide[NotRegistered]):
                return dep


def test_inject_async_function_preserves_metadata():
    """The wrapper of an async function keeps the original's name, qualname, docstring and __wrapped__"""
    with Injector.context(InjectionSubcontextType.RESET):
        @Injector.singleton
        class Dep:
            pass

        async def fn(dep: Provide[Dep]):
            """Original docstring"""
            return dep

        wrapped = Injector.inject(fn)
        assert wrapped.__name__ == fn.__name__
        assert wrapped.__qualname__ == fn.__qualname__
        assert wrapped.__doc__ == fn.__doc__
        assert wrapped.__wrapped__ is fn


def test_module_level_predicates(reset_injector):
    """issingleton and isinterface answer like Injector.is_singleton and Injector.is_interface, for the current context"""
    class Plain:
        pass

    class Base(ABC):
        @abstractmethod
        def run(self): ...

    assert not issingleton(Plain)
    assert not isinterface(Plain)
    assert not isinterface(Base)

    @Injector.singleton
    class Service:
        pass

    Injector.interface(Base)

    assert issingleton(Service)
    assert not isinterface(Service)
    assert isinterface(Base)
    assert not issingleton(Base)

    with Injector.context(InjectionSubcontextType.RESET):
        class Late:
            pass

        Injector.singleton(Late)
        assert issingleton(Late)
        assert issingleton(Service)
    assert not issingleton(Late)


def test_module_level_decorators(reset_injector):
    """singleton, interface, implements, override and inject behave like the Injector classmethods"""
    @interface
    class Greeter(ABC):
        @abstractmethod
        def greet(self) -> str: ...

    @implements(Greeter)
    @singleton
    class Plain(Greeter):
        def greet(self) -> str:
            return "hello"

    @singleton
    class Counter:
        pass

    @override(Counter)
    @singleton
    class BetterCounter(Counter):
        pass

    @inject
    def use(greeter: Provide[Greeter], counter: Provide[Counter]):
        return greeter.greet(), counter

    assert isinterface(Greeter)
    assert issingleton(Plain)
    assert issingleton(Counter)
    greeting, counter = use()
    assert greeting == "hello"
    assert isinstance(counter, BetterCounter)
    assert counter is Injector.get_instance(Counter)

    with pytest.raises(TypeError):
        interface(Plain)
    with pytest.raises(TypeError):
        singleton(Counter)

    @override(Counter, when=lambda: False)
    class Skipped(Counter):
        pass

    assert not issingleton(Skipped)
