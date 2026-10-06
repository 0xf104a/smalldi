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


def make_cache():
    @Injector.interface
    class Cache(ABC):
        @abstractmethod
        def ping(self) -> str:
            pass

    return Cache


class _AbstractA(ABC):
    @abstractmethod
    def run(self):
        pass


class _ConcreteA(_AbstractA):
    def run(self):
        pass


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

    Cache = make_cache()

    @Injector.implements(Storage, Cache)
    @Injector.singleton
    class RedisStorage(Storage, Cache):
        def name(self):
            return "redis"

        def ping(self):
            return "pong"

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

    Cache = make_cache()

    with pytest.raises(TypeError):
        @Injector.implements(Storage, Cache)
        @Injector.singleton
        class OnlyStorage(Storage):
            def name(self):
                return "storage"

    assert Injector._interface_resolver.resolve(Storage).implementation is None


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


def test_interface_must_be_abstract(reset_injector):
    class Concrete:
        pass

    with pytest.raises(TypeError, match="not abstract"):
        Injector.interface(Concrete)
    assert not Injector._interface_resolver.is_interface(Concrete)


def test_interface_cannot_be_singleton(reset_injector):
    Storage = make_storage()

    with pytest.raises(TypeError):
        Injector.singleton(Storage)


def test_singleton_cannot_be_interface(reset_injector):
    @Injector.singleton
    class Service:
        pass

    with pytest.raises(TypeError):
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


class TestInterfaceResolver:
    def test_unregistered_interface(self):
        resolver = InterfaceResolver()
        assert not resolver.is_interface(_AbstractA)
        with pytest.raises(TypeError):
            resolver.resolve(_AbstractA)

    def test_register_requires_abstract(self):
        resolver = InterfaceResolver()
        with pytest.raises(TypeError):
            resolver.register(object)

    def test_registered_interface_has_own_singleton(self):
        resolver = InterfaceResolver()
        resolver.register(_AbstractA)
        singleton = resolver.resolve(_AbstractA)
        assert resolver.is_interface(_AbstractA)
        assert singleton.cls is _AbstractA
        assert not singleton.resolvable
        assert list(resolver.interfaces()) == [_AbstractA]
        assert list(resolver.singletons()) == [singleton]
        with pytest.raises(NotImplementedError):
            singleton.get_instance()

    def test_register_again_drops_bindings(self):
        resolver = InterfaceResolver()
        resolver.register(_AbstractA)
        resolver.resolve(_AbstractA).override(LazySingleton(_ConcreteA))
        resolver.register(_AbstractA)
        assert resolver.resolve(_AbstractA).override_singleton is None


def make_memory_storage(Storage):
    @Injector.implements(Storage)
    @Injector.singleton
    class MemoryStorage(Storage):
        def name(self):
            return "memory"

    return MemoryStorage


def test_override_rebinds_interface(reset_injector):
    Storage = make_storage()
    MemoryStorage = make_memory_storage(Storage)

    @Injector.override(Storage)
    @Injector.singleton
    class FakeStorage(Storage):
        def name(self):
            return "fake"

    @Injector.inject
    def fn(storage: Provide[Storage], memory: Provide[MemoryStorage]):
        return storage, memory

    storage, memory = fn()
    assert isinstance(storage, FakeStorage)
    # The old implementation stays injectable by its own class
    assert isinstance(memory, MemoryStorage)


def test_override_returns_class_unchanged(reset_injector):
    Storage = make_storage()
    make_memory_storage(Storage)

    class FakeStorage(Storage):
        def name(self):
            return "fake"

    Injector.singleton(FakeStorage)
    assert Injector.override(Storage)(FakeStorage) is FakeStorage


def test_second_override_raises(reset_injector):
    Storage = make_storage()
    make_memory_storage(Storage)

    @Injector.override(Storage)
    @Injector.singleton
    class First(Storage):
        def name(self):
            return "first"

    with pytest.raises(TypeError, match="already overridden"):
        @Injector.override(Storage)
        @Injector.singleton
        class Second(Storage):
            def name(self):
                return "second"

    assert isinstance(Injector._get_instance(Storage), First)


def test_override_same_class_twice_is_allowed(reset_injector):
    Storage = make_storage()

    @Injector.override(Storage)
    @Injector.singleton
    class FakeStorage(Storage):
        def name(self):
            return "fake"

    Injector.override(Storage)(FakeStorage)
    assert isinstance(Injector._get_instance(Storage), FakeStorage)


def test_reloaded_override_rebinds(reset_injector):
    Storage = make_storage()

    def make_fake():
        class FakeStorage(Storage):
            def name(self):
                return "fake"
        return FakeStorage

    first = Injector.override(Storage)(Injector.singleton(make_fake()))
    with pytest.warns(RuntimeWarning):
        second = Injector.singleton(make_fake())
    Injector.override(Storage)(second)

    assert type(Injector._get_instance(Storage)) is second
    assert second is not first


def test_override_multiple_interfaces(reset_injector):
    Storage = make_storage()

    Cache = make_cache()

    @Injector.implements(Storage, Cache)
    @Injector.singleton
    class RedisStorage(Storage, Cache):
        def name(self):
            return "redis"

        def ping(self):
            return "pong"

    @Injector.override(Storage, Cache)
    @Injector.singleton
    class FakeStorage(Storage, Cache):
        def name(self):
            return "fake"

        def ping(self):
            return "fake pong"

    assert Injector._get_instance(Storage) is Injector._get_instance(Cache)
    assert isinstance(Injector._get_instance(Cache), FakeStorage)


def test_override_requires_interfaces(reset_injector):
    with pytest.raises(TypeError):
        Injector.override()


def test_override_requires_singleton(reset_injector):
    Storage = make_storage()
    make_memory_storage(Storage)

    with pytest.raises(TypeError, match="above @Injector.singleton"):
        @Injector.singleton
        @Injector.override(Storage)
        class FakeStorage(Storage):
            def name(self):
                return "fake"


def test_override_requires_registered_interface(reset_injector):
    class NotInterface:
        pass

    with pytest.raises(TypeError, match="neither an interface nor a singleton"):
        @Injector.override(NotInterface)
        @Injector.singleton
        class Impl(NotInterface):
            pass


def test_override_requires_subclass(reset_injector):
    Storage = make_storage()
    make_memory_storage(Storage)

    with pytest.raises(TypeError, match="not a subclass"):
        @Injector.override(Storage)
        @Injector.singleton
        class Unrelated:
            pass


def test_override_before_implementation_wins(reset_injector):
    """An override module may be imported before the implementation module"""
    Storage = make_storage()

    @Injector.override(Storage)
    @Injector.singleton
    class FakeStorage(Storage):
        def name(self):
            return "fake"

    @Injector.inject
    def fn(storage: Provide[Storage]):
        return storage

    MemoryStorage = make_memory_storage(Storage)

    assert isinstance(fn(), FakeStorage)
    assert Injector._interface_resolver.resolve(Storage).implementation.cls is MemoryStorage


def test_override_without_implementation_is_injected(reset_injector):
    Storage = make_storage()

    @Injector.override(Storage)
    @Injector.singleton
    class FakeStorage(Storage):
        def name(self):
            return "fake"

    assert isinstance(Injector._get_instance(Storage), FakeStorage)


def test_implementation_after_injected_override_is_allowed(reset_injector):
    """Declaring the implementation late doesn't change what was injected"""
    Storage = make_storage()

    @Injector.override(Storage)
    @Injector.singleton
    class FakeStorage(Storage):
        def name(self):
            return "fake"

    first = Injector._get_instance(Storage)
    make_memory_storage(Storage)
    assert Injector._get_instance(Storage) is first


def test_override_after_injection_is_rejected(reset_injector):
    Storage = make_storage()
    MemoryStorage = make_memory_storage(Storage)

    @Injector.inject
    def fn(storage: Provide[Storage]):
        return storage

    fn()

    with pytest.raises(SingletonFrozenError):
        @Injector.override(Storage)
        @Injector.singleton
        class FakeStorage(Storage):
            def name(self):
                return "fake"

    assert isinstance(fn(), MemoryStorage)


def test_override_after_reading_singletons_is_rejected(reset_injector):
    Storage = make_storage()
    make_memory_storage(Storage)

    @Injector.singleton
    class FakeStorage(Storage):
        def name(self):
            return "fake"

    Injector.singletons
    with pytest.raises(SingletonFrozenError):
        Injector.override(Storage)(FakeStorage)


def test_override_allowed_when_only_implementation_was_injected(reset_injector):
    """Injecting the implementation class directly doesn't freeze its interfaces"""
    Storage = make_storage()
    MemoryStorage = make_memory_storage(Storage)

    @Injector.inject
    def fn(memory: Provide[MemoryStorage]):
        return memory

    fn()

    @Injector.override(Storage)
    @Injector.singleton
    class FakeStorage(Storage):
        def name(self):
            return "fake"

    assert isinstance(Injector._get_instance(Storage), FakeStorage)


def test_override_binds_all_or_nothing(reset_injector):
    Storage = make_storage()
    Cache = make_cache()

    @Injector.override(Cache)
    @Injector.singleton
    class FakeCache(Cache):
        def ping(self):
            return "fake pong"

    with pytest.raises(TypeError, match="already overridden"):
        @Injector.override(Storage, Cache)
        @Injector.singleton
        class FakeStorage(Storage, Cache):
            def name(self):
                return "fake"

            def ping(self):
                return "pong"

    assert Injector._interface_resolver.resolve(Storage).override_singleton is None


def test_second_implementation_raises_despite_override(reset_injector):
    Storage = make_storage()
    make_memory_storage(Storage)

    @Injector.override(Storage)
    @Injector.singleton
    class FakeStorage(Storage):
        def name(self):
            return "fake"

    with pytest.raises(TypeError, match="@Injector.override"):
        @Injector.implements(Storage)
        @Injector.singleton
        class Another(Storage):
            def name(self):
                return "another"


def test_interface_reregistration_unfreezes(reset_injector):
    Storage = make_storage()
    make_memory_storage(Storage)
    Injector._get_instance(Storage)
    assert Injector._interface_resolver.resolve(Storage).frozen

    with pytest.warns(RuntimeWarning):
        Injector.interface(Storage)
    assert not Injector._interface_resolver.resolve(Storage).frozen


def test_singleton_frozen_error_is_public():
    import smalldi
    assert smalldi.SingletonFrozenError is SingletonFrozenError
    assert "SingletonFrozenError" in smalldi.__all__


def test_reregistered_implementation_keeps_interface_binding(reset_injector):
    Storage = make_storage()
    MemoryStorage = make_memory_storage(Storage)

    with pytest.warns(RuntimeWarning):
        Injector.singleton(MemoryStorage)
    fresh = Injector._singletons_available[MemoryStorage]
    assert Injector._interface_resolver.resolve(Storage).implementation is fresh
    assert Injector._get_instance(Storage) is fresh.get_instance()
