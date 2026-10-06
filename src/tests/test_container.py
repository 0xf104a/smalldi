import threading

import pytest

from smalldi import Injector, _Provide, Provide
from smalldi import container as container_module
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


def test_container_inherits_components_of_base_container(reset_injector):
    calls = []

    @Injector.singleton
    class BaseContainer(Container):
        pass

    @BaseContainer.component()
    def before():
        return None

    @Injector.singleton
    class ChildContainer(BaseContainer):
        def _on_component_register(self, registration: ComponentRegistration):
            calls.append(registration.component)

    @BaseContainer.component()
    def after():
        return None

    @Injector.inject
    def fn(container: Provide[ChildContainer]):
        return container

    container = fn()
    assert list(container._get_components()) == [before, after]
    assert calls == [before, after]


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


def test_reset_injector_resets_container_state(reset_injector):
    # Earlier tests in this module registered components and created containers
    assert container_module._registrations == []
    assert container_module._instances == []


def test_component_hook_resolving_singleton_does_not_deadlock(reset_injector):
    # Thread A creates Service, whose constructor registers a component; meanwhile thread B registers
    # a component whose hook resolves Service. Library locks must not be held while running the hook
    service_creating = threading.Event()
    hook_running = threading.Event()

    @Injector.singleton
    class MyContainer(Container):
        def _on_component_register(self, registration: ComponentRegistration):
            if registration.args == ("resolve",):
                hook_running.set()
                get_service()

    class Service:
        def __init__(self):
            service_creating.set()
            hook_running.wait(timeout=5)
            MyContainer.component()(lambda: None)

    Injector.singleton(Service)

    @Injector.inject
    def get_service(service: Provide[Service]):
        return service

    @Injector.inject
    def get_container(container: Provide[MyContainer]):
        return container

    get_container()

    def register_resolving():
        service_creating.wait(timeout=5)
        MyContainer.component("resolve")(lambda: None)

    threads = [threading.Thread(target=get_service, daemon=True),
               threading.Thread(target=register_resolving, daemon=True)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert not any(t.is_alive() for t in threads), "threads deadlocked"
