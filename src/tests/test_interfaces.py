from abc import ABC, abstractmethod

import pytest

from smalldi import Injector, Provide
from smalldi._interfaces import InterfaceResolver
from smalldi._singleton import LazySingleton, SingletonFrozenError


def make_storage():
    @Injector.interface
    class Storage(ABC):
        @abstractmethod
        def name(self) -> str:
            pass

    return Storage


def test_inject_interface_receives_implementation(reset_injector):
    Storage = make_storage()

    @Injector.implements(Storage)
    @Injector.singleton
    class MemoryStorage(Storage):
        def name(self):
            return "memory"

    @Injector.inject
    def fn(storage: Provide[Storage], direct: Provide[MemoryStorage]):
        return storage, direct

    storage, direct = fn()
    assert storage.name() == "memory"
    # The interface and the class share one instance
    assert storage is direct


def test_implements_returns_class_unchanged(reset_injector):
    Storage = make_storage()

    class MemoryStorage(Storage):
        def name(self):
            return "memory"

    Injector.singleton(MemoryStorage)
    assert Injector.implements(Storage)(MemoryStorage) is MemoryStorage


def test_implements_multiple_interfaces(reset_injector):
    Storage = make_storage()

    @Injector.interface
    class Cache:
        pass

    @Injector.implements(Storage, Cache)
    @Injector.singleton
    class RedisStorage(Storage, Cache):
        def name(self):
            return "redis"

    @Injector.inject
    def fn(storage: Provide[Storage], cache: Provide[Cache]):
        return storage, cache

    storage, cache = fn()
    assert storage is cache
    assert isinstance(storage, RedisStorage)


def test_implementation_may_be_declared_after_inject(reset_injector):
    Storage = make_storage()

    @Injector.inject
    def fn(storage: Provide[Storage]):
        return storage

    with pytest.raises(NotImplementedError):
        fn()

    @Injector.implements(Storage)
    @Injector.singleton
    class MemoryStorage(Storage):
        def name(self):
            return "memory"

    assert isinstance(fn(), MemoryStorage)


def test_explicit_kwarg_wins_over_interface(reset_injector):
    Storage = make_storage()

    @Injector.inject
    def fn(storage: Provide[Storage]):
        return storage

    sentinel = object()
    # No implementation needed when the argument is passed explicitly
    assert fn(storage=sentinel) is sentinel


def test_implements_requires_interfaces(reset_injector):
    with pytest.raises(TypeError):
        Injector.implements()


def test_implements_requires_singleton(reset_injector):
    Storage = make_storage()

    with pytest.raises(TypeError, match="above @Injector.singleton"):
        @Injector.singleton
        @Injector.implements(Storage)
        class MemoryStorage(Storage):
            def name(self):
                return "memory"


def test_implements_requires_registered_interface(reset_injector):
    class NotInterface:
        pass

    with pytest.raises(TypeError, match="not an interface"):
        @Injector.implements(NotInterface)
        @Injector.singleton
        class Impl(NotInterface):
            pass


def test_implements_requires_subclass(reset_injector):
    Storage = make_storage()

    with pytest.raises(TypeError, match="not a subclass"):
        @Injector.implements(Storage)
        @Injector.singleton
        class Unrelated:
            pass


def test_implements_accepts_virtual_subclass(reset_injector):
    Storage = make_storage()

    @Injector.implements(Storage)
    @Injector.singleton
    @Storage.register
    class Virtual:
        def name(self):
            return "virtual"

    assert isinstance(Injector._get_instance(Storage), Virtual)


def test_interface_has_one_implementation(reset_injector):
    Storage = make_storage()

    @Injector.implements(Storage)
    @Injector.singleton
    class First(Storage):
        def name(self):
            return "first"

    with pytest.raises(TypeError, match="already implemented"):
        @Injector.implements(Storage)
        @Injector.singleton
        class Second(Storage):
            def name(self):
                return "second"


def test_implements_binds_all_or_nothing(reset_injector):
    Storage = make_storage()

    @Injector.interface
    class Cache:
        pass

    with pytest.raises(TypeError):
        @Injector.implements(Storage, Cache)
        @Injector.singleton
        class OnlyStorage(Storage):
            def name(self):
                return "storage"

    assert Injector._interface_resolver.implementation_of(Storage) is None


def test_implements_same_class_twice_is_allowed(reset_injector):
    Storage = make_storage()

    @Injector.implements(Storage)
    @Injector.singleton
    class MemoryStorage(Storage):
        def name(self):
            return "memory"

    Injector.implements(Storage)(MemoryStorage)
    assert isinstance(Injector._get_instance(Storage), MemoryStorage)


def test_reloaded_implementation_rebinds(reset_injector):
    Storage = make_storage()

    def make_impl():
        class MemoryStorage(Storage):
            def name(self):
                return "memory"
        return MemoryStorage

    first = Injector.implements(Storage)(Injector.singleton(make_impl()))
    with pytest.warns(RuntimeWarning):
        second = Injector.singleton(make_impl())
    Injector.implements(Storage)(second)

    instance = Injector._get_instance(Storage)
    assert type(instance) is second
    assert type(instance) is not first


def test_interface_cannot_be_singleton(reset_injector):
    @Injector.interface
    class Concrete:
        pass

    with pytest.raises(TypeError, match="interface"):
        Injector.singleton(Concrete)


def test_singleton_cannot_be_interface(reset_injector):
    @Injector.singleton
    class Service:
        pass

    with pytest.raises(TypeError, match="singleton"):
        Injector.interface(Service)


def test_interface_reregistration_warns_and_drops_implementation(reset_injector):
    Storage = make_storage()

    @Injector.implements(Storage)
    @Injector.singleton
    class MemoryStorage(Storage):
        def name(self):
            return "memory"

    with pytest.warns(RuntimeWarning):
        Injector.interface(Storage)
    with pytest.raises(NotImplementedError):
        Injector._get_instance(Storage)


def test_interface_reload_warns(reset_injector):
    make_storage()
    with pytest.warns(RuntimeWarning):
        make_storage()


def test_singletons_view_excludes_interfaces(reset_injector):
    Storage = make_storage()

    @Injector.implements(Storage)
    @Injector.singleton
    class MemoryStorage(Storage):
        def name(self):
            return "memory"

    assert set(Injector.singletons) == {MemoryStorage}


def test_override_through_interface_before_freeze(reset_injector):
    Storage = make_storage()

    @Injector.implements(Storage)
    @Injector.singleton
    class MemoryStorage(Storage):
        def name(self):
            return "memory"

    class FakeStorage(MemoryStorage):
        def name(self):
            return "fake"

    Injector._interface_resolver.override_implementation(Storage, FakeStorage)
    assert Injector._get_instance(Storage).name() == "fake"


def test_override_through_interface_after_freeze(reset_injector):
    Storage = make_storage()

    @Injector.implements(Storage)
    @Injector.singleton
    class MemoryStorage(Storage):
        def name(self):
            return "memory"

    class FakeStorage(MemoryStorage):
        pass

    Injector._get_instance(Storage)
    with pytest.raises(SingletonFrozenError):
        Injector._interface_resolver.override_implementation(Storage, FakeStorage)


class TestInterfaceResolver:
    def test_unregistered_interface(self):
        resolver = InterfaceResolver()
        with pytest.raises(TypeError):
            resolver.resolve(object)
        with pytest.raises(TypeError):
            resolver.implementation_of(object)
        with pytest.raises(TypeError):
            resolver.set_implementation(object, LazySingleton(object, None))
        with pytest.raises(TypeError):
            resolver.override_implementation(object, object)

    def test_unimplemented_interface(self):
        resolver = InterfaceResolver()
        resolver.register(object)
        assert resolver.is_interface(object)
        assert resolver.implementation_of(object) is None
        with pytest.raises(NotImplementedError):
            resolver.resolve(object)
        with pytest.raises(NotImplementedError):
            resolver.override_implementation(object, object)

    def test_resolve_bound_interface(self):
        resolver = InterfaceResolver()
        singleton = LazySingleton(int, None)
        resolver.register(object)
        resolver.set_implementation(object, singleton)
        assert resolver.resolve(object) is singleton
        assert list(resolver.interfaces()) == [object]
