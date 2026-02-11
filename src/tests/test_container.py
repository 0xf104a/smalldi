import pytest

from smalldi import Injector
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
    inst = Injector.singletons_available[MyContainer]
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

    inst = Injector.singletons_available[MyContainer]
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

    inst = Injector.singletons_available[MyContainer]
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

    assert len(calls) == 1
    assert isinstance(calls[0], ComponentRegistration)
    assert calls[0].component is comp
    assert calls[0].args == ("x",)
    assert calls[0].kwargs == {"kind": "k"}
    singleton = Injector.singletons_available[MyContainer]
    assert singleton.components == calls

def test_component_raises_if_not_singleton_at_decoration_time(reset_injector):
    class MyContainer(Container):
        pass

    def fn():
        return 1

    with pytest.raises(TypeError, match="Injector must be a singleton to use components"):
        MyContainer.component()(fn)