from abc import ABC, abstractmethod

import pytest

from smalldi import Injector, Provide, InterfaceAlreadyBoundError, SingletonFrozenError
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
    assert isinstance(Injector._singletons_available[TestService], TestService)

    service = Injector._singletons_available[TestService]
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

    with pytest.raises(ValueError, match="already marked as singleton"):
        Injector.singleton(TestService)
    assert counter == 1


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


def test_override_singleton(reset_injector):
    @Injector.singleton
    class Base:
        def value(self):
            return "base"

    @Injector.override(Base)
    @Injector.singleton
    class Override(Base):
        def value(self):
            return "override"

    @Injector.inject
    def fn(base: Provide[Base], override: Provide[Override]):
        return base, override

    base, override = fn()
    assert base is override
    assert base.value() == "override"


def test_override_singleton_skipped_when_predicate_false(reset_injector):
    @Injector.singleton
    class Base:
        pass

    @Injector.override(Base, on=lambda: False)
    @Injector.singleton
    class Override(Base):
        pass

    @Injector.inject
    def fn(base: Provide[Base]):
        return base

    assert type(fn()) is Base


def test_override_singleton_requires_subclass(reset_injector):
    @Injector.singleton
    class Base:
        pass

    with pytest.raises(TypeError, match="does not implement"):
        @Injector.override(Base)
        @Injector.singleton
        class Unrelated:
            pass


def test_override_singleton_requires_singleton(reset_injector):
    @Injector.singleton
    class Base:
        pass

    with pytest.raises(TypeError, match="must be a singleton"):
        @Injector.override(Base)
        class Override(Base):
            pass


def test_override_singleton_twice_raises_already_bound(reset_injector):
    @Injector.singleton
    class Base:
        pass

    @Injector.override(Base)
    @Injector.singleton
    class First(Base):
        pass

    with pytest.raises(InterfaceAlreadyBoundError) as exc_info:
        @Injector.override(Base)
        @Injector.singleton
        class Second(Base):
            pass
    assert exc_info.value.bound_target is First


def test_override_singleton_after_injection_raises_frozen(reset_injector):
    @Injector.singleton
    class Base:
        pass

    @Injector.inject
    def fn(base: Provide[Base]):
        return base

    with pytest.raises(SingletonFrozenError) as exc_info:
        @Injector.override(Base)
        @Injector.singleton
        class Override(Base):
            pass
    assert exc_info.value.singleton_cls is Base
    # Failed override doesn't change what was injected
    assert type(fn()) is Base


def test_override_singleton_chain(reset_injector):
    @Injector.singleton
    class Base:
        pass

    @Injector.override(Base)
    @Injector.singleton
    class Middle(Base):
        pass

    @Injector.override(Middle)
    @Injector.singleton
    class Leaf(Middle):
        pass

    @Injector.inject
    def fn(base: Provide[Base]):
        return base

    assert type(fn()) is Leaf
    # Every singleton on the chain is frozen
    with pytest.raises(SingletonFrozenError):
        @Injector.override(Leaf)
        @Injector.singleton
        class AfterLeaf(Leaf):
            pass


class _Bowl(ABC):
    @abstractmethod
    def fill(self) -> str:
        pass


def test_override_singleton_overrides_interface_baseline(reset_injector):
    @Injector.implements(_Bowl)
    @Injector.singleton
    class FishBowl(_Bowl):
        def fill(self):
            return "fish"

    @Injector.override(FishBowl)
    @Injector.singleton
    class MilkBowl(FishBowl):
        def fill(self):
            return "milk"

    @Injector.inject
    def fn(bowl: Provide[_Bowl], fish: Provide[FishBowl]):
        return bowl.fill(), fish.fill()

    assert fn() == ("milk", "milk")


def test_override_singleton_overrides_interface_override(reset_injector):
    @Injector.implements(_Bowl)
    @Injector.singleton
    class FishBowl(_Bowl):
        def fill(self):
            return "fish"

    @Injector.override(_Bowl)
    @Injector.singleton
    class MilkBowl(_Bowl):
        def fill(self):
            return "milk"

    @Injector.override(MilkBowl)
    @Injector.singleton
    class CreamBowl(MilkBowl):
        def fill(self):
            return "cream"

    @Injector.inject
    def fn(bowl: Provide[_Bowl]):
        return bowl.fill()

    assert fn() == "cream"


def test_override_singleton_after_interface_injection_raises_frozen(reset_injector):
    @Injector.implements(_Bowl)
    @Injector.singleton
    class FishBowl(_Bowl):
        def fill(self):
            return "fish"

    @Injector.inject
    def fn(bowl: Provide[_Bowl]):
        return bowl.fill()

    with pytest.raises(SingletonFrozenError):
        @Injector.override(FishBowl)
        @Injector.singleton
        class MilkBowl(FishBowl):
            def fill(self):
                return "milk"
    assert fn() == "fish"

