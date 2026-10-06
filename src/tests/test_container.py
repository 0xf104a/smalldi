import pytest

from smalldi import Injector, _Provide, Provide
from smalldi.container import Container, ComponentRegistration


def test_component_requires_container_singleton(reset_injector):
    class MyContainer(Container):
        pass

    with pytest.raises(TypeError, match="Injector must be a singleton to use components"):
        @MyContainer.component()
        def some_component():
            return 123


def test_component_registers_component_and_returns_object(reset_injector):
    @Injector.singleton
    class MyContainer(Container):
        pass

    def fn():
        return "ok"

    decorated = MyContainer.component()(fn)

    # Повертає об'єкт без змін
    assert decorated is fn

    # Реєстрація зберігається в singleton-інстансі контейнера
    inst = Injector._singletons_available[MyContainer].get()
    assert len(inst.components) == 1
    reg = inst.components[0]
    assert isinstance(reg, ComponentRegistration)
    assert reg.component is fn
    assert reg.args == ()
    assert reg.kwargs == {}


def test_component_registers_metadata_args_kwargs(reset_injector):
    @Injector.singleton
    class MyContainer(Container):
        pass

    @MyContainer.component("tag-a", 123, role="service", enabled=True)
    class Service:
        pass

    inst = Injector._singletons_available[MyContainer].get()
    assert len(inst.components) == 1
    reg = inst.components[0]
    assert reg.component is Service
    assert reg.args == ("tag-a", 123)
    assert reg.kwargs == {"role": "service", "enabled": True}


def test_get_components_yields_only_components_in_order(reset_injector):
    @Injector.singleton
    class MyContainer(Container):
        pass

    @MyContainer.component()
    def a():
        return "a"

    @MyContainer.component()
    class B:
        pass

    inst = Injector._singletons_available[MyContainer].get()
    assert list(inst._get_components()) == [a, B]


def test_on_component_register_is_called_with_registration(reset_injector):
    calls: list[ComponentRegistration] = []

    @Injector.singleton
    class MyContainer(Container):
        def _on_component_register(self, registration: ComponentRegistration):
            calls.append(registration)

    @MyContainer.component("x", kind="k")
    def comp():
        return None

    # The container is created lazily; registrations made before are replayed on creation
    assert calls == []
    singleton = Injector._singletons_available[MyContainer].get()
    assert len(calls) == 1
    assert isinstance(calls[0], ComponentRegistration)
    assert calls[0].component is comp
    assert calls[0].args == ("x",)
    assert calls[0].kwargs == {"kind": "k"}

    # Once the container exists, the hook is called on registration
    @MyContainer.component()
    def later():
        return None

    assert len(calls) == 2
    assert calls[1].component is later
    assert singleton.components == calls

def test_component_raises_if_not_singleton_at_decoration_time(reset_injector):
    class MyContainer(Container):
        pass

    def fn():
        return 1

    with pytest.raises(TypeError, match="Injector must be a singleton to use components"):
        MyContainer.component()(fn)

def test_component_injection(reset_injector):
    @Injector.singleton
    class MyContainer(Container):
        pass

    @Injector.singleton
    class MySingleton:
        def magic_value(self):
            return 42

    @MyContainer.component()
    class MyComponent:
        @Injector.inject
        def __init__(self, value: Provide[MySingleton]):
            self.value = value.magic_value()

    @Injector.inject
    def test_function(service: Provide[MySingleton]):
        return service

    assert test_function().magic_value() == 42
    assert MyComponent().value == 42


def test_components_registered_on_overridden_container(reset_injector):
    calls = []

    @Injector.singleton
    class MyContainer(Container):
        pass

    @MyContainer.component()
    def before_override():
        return None

    @Injector.override(MyContainer)
    @Injector.singleton
    class TestContainer(MyContainer):
        def _on_component_register(self, registration: ComponentRegistration):
            calls.append(registration.component)

    @MyContainer.component()
    def after_override():
        return None

    @Injector.inject
    def fn(container: Provide[MyContainer]):
        return container

    container = fn()
    assert type(container) is TestContainer
    assert list(container._get_components()) == [before_override, after_override]
    # The hook is called once per registration, even though two singletons resolve to the container
    assert calls == [before_override, after_override]


def test_container_is_not_created_by_registration(reset_injector):
    created = 0

    @Injector.singleton
    class MyContainer(Container):
        def __init__(self):
            nonlocal created
            created += 1

    @MyContainer.component()
    def comp():
        return None

    assert created == 0
