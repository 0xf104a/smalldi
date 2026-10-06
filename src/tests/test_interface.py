import threading
from abc import ABC, abstractmethod

import pytest

from smalldi import Injector, Provide, InterfaceFrozenError
from smalldi._interface import InterfaceTable


class Storage(ABC):
    @abstractmethod
    def load(self) -> str:
        pass


class DiskStorage(Storage):
    def load(self) -> str:
        return "disk"


class MemoryStorage(Storage):
    def load(self) -> str:
        return "memory"


class PartialStorage(Storage):
    pass


# InterfaceTable

def test_unbound_interface_returns_none():
    table = InterfaceTable()
    assert table.get_interface_impl(Storage) is None
    assert not table.is_frozen(Storage)


def test_set_and_get_impl():
    table = InterfaceTable()
    table.set_interface_impl(Storage, DiskStorage)
    assert table.get_interface_impl(Storage) is DiskStorage


def test_rebind_before_lookup_replaces_impl():
    table = InterfaceTable()
    table.set_interface_impl(Storage, DiskStorage)
    table.set_interface_impl(Storage, MemoryStorage)
    assert table.get_interface_impl(Storage) is MemoryStorage


def test_lookup_freezes_binding():
    table = InterfaceTable()
    table.set_interface_impl(Storage, DiskStorage)
    assert not table.is_frozen(Storage)
    table.get_interface_impl(Storage)
    assert table.is_frozen(Storage)

    with pytest.raises(InterfaceFrozenError) as exc_info:
        table.set_interface_impl(Storage, MemoryStorage)
    err = exc_info.value
    assert err.interface is Storage
    assert err.resolved_target is DiskStorage
    assert err.rebind_target is MemoryStorage
    assert "DiskStorage" in str(err) and "MemoryStorage" in str(err)
    assert table.get_interface_impl(Storage) is DiskStorage


def test_rebind_same_impl_after_freeze_is_noop():
    table = InterfaceTable()
    table.set_interface_impl(Storage, DiskStorage)
    table.get_interface_impl(Storage)
    table.set_interface_impl(Storage, DiskStorage)
    assert table.get_interface_impl(Storage) is DiskStorage


def test_lookup_of_unbound_interface_does_not_freeze():
    table = InterfaceTable()
    table.get_interface_impl(Storage)
    assert not table.is_frozen(Storage)
    table.set_interface_impl(Storage, DiskStorage)
    assert table.get_interface_impl(Storage) is DiskStorage


@pytest.mark.parametrize("interface, impl, match", [
    (Storage, int, "does not implement"),
    (Storage, Storage, "does not implement"),
    (Storage, PartialStorage, "leaves abstract members .*: load"),
    (Storage, DiskStorage(), "Implementation must be a class"),
    ("Storage", DiskStorage, "Interface must be a class"),
])
def test_invalid_bindings_raise_type_error(interface, impl, match):
    table = InterfaceTable()
    with pytest.raises(TypeError, match=match):
        table.set_interface_impl(interface, impl)
    assert table.get_interface_impl(Storage) is None


def test_concurrent_lookup_and_rebind_is_consistent():
    table = InterfaceTable()
    table.set_interface_impl(Storage, DiskStorage)
    seen = []
    errors = []

    def lookup():
        seen.append(table.get_interface_impl(Storage))

    def rebind():
        try:
            table.set_interface_impl(Storage, MemoryStorage)
        except InterfaceFrozenError as e:
            errors.append(e)

    threads = [threading.Thread(target=f) for _ in range(20) for f in (lookup, rebind)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Every lookup saw the same implementation, and rebinding succeeded only if it happened before any lookup
    assert len(set(seen)) == 1
    assert table.get_interface_impl(Storage) is seen[0]


# Injector integration

def test_provide_interface_injects_implementation(reset_injector):
    @Injector.implements(Storage)
    @Injector.singleton
    class Impl(Storage):
        def load(self) -> str:
            return "impl"

    @Injector.inject
    def fn(storage: Provide[Storage]):
        return storage

    assert isinstance(fn(), Impl)
    assert fn() is Injector._singletons_available[Impl]
    assert fn().load() == "impl"


def test_implements_returns_class_unaltered(reset_injector):
    @Injector.singleton
    class Impl(Storage):
        def load(self) -> str:
            return "impl"

    assert Injector.implements(Storage)(Impl) is Impl


def test_implementation_is_also_injectable_directly(reset_injector):
    @Injector.implements(Storage)
    @Injector.singleton
    class Impl(Storage):
        def load(self) -> str:
            return "impl"

    @Injector.inject
    def fn(by_iface: Provide[Storage], by_impl: Provide[Impl]):
        return by_iface, by_impl

    by_iface, by_impl = fn()
    assert by_iface is by_impl


def test_implements_requires_singleton(reset_injector):
    with pytest.raises(TypeError, match="must be a singleton"):
        @Injector.singleton
        @Injector.implements(Storage)
        class Impl(Storage):
            def load(self) -> str:
                return "impl"


def test_implements_rejects_non_implementation(reset_injector):
    @Injector.singleton
    class NotStorage:
        pass

    with pytest.raises(TypeError, match="does not implement"):
        Injector.implements(Storage)(NotStorage)


def test_unbound_interface_is_not_available(reset_injector):
    with pytest.raises(TypeError, match="is not available"):
        @Injector.inject
        def fn(storage: Provide[Storage]):
            return storage


def test_rebind_before_injection_wins(reset_injector):
    @Injector.implements(Storage)
    @Injector.singleton
    class First(Storage):
        def load(self) -> str:
            return "first"

    @Injector.implements(Storage)
    @Injector.singleton
    class Second(Storage):
        def load(self) -> str:
            return "second"

    @Injector.inject
    def fn(storage: Provide[Storage]):
        return storage.load()

    assert fn() == "second"


def test_rebind_after_injection_raises(reset_injector):
    @Injector.implements(Storage)
    @Injector.singleton
    class First(Storage):
        def load(self) -> str:
            return "first"

    @Injector.inject
    def fn(storage: Provide[Storage]):
        return storage.load()

    with pytest.raises(InterfaceFrozenError):
        @Injector.implements(Storage)
        @Injector.singleton
        class Second(Storage):
            def load(self) -> str:
                return "second"

    assert fn() == "first"


def test_explicit_argument_overrides_interface_injection(reset_injector):
    @Injector.implements(Storage)
    @Injector.singleton
    class Impl(Storage):
        def load(self) -> str:
            return "impl"

    @Injector.inject
    def fn(storage: Provide[Storage]):
        return storage.load()

    assert fn(storage=MemoryStorage()) == "memory"


def test_singleton_constructor_receives_interface(reset_injector):
    @Injector.implements(Storage)
    @Injector.singleton
    class Impl(Storage):
        def load(self) -> str:
            return "impl"

    @Injector.singleton
    class Service:
        @Injector.inject
        def __init__(self, storage: Provide[Storage]):
            self.data = storage.load()

    assert Injector._singletons_available[Service].data == "impl"


def test_singletons_available_alias_is_deprecated(reset_injector):
    @Injector.singleton
    class Service:
        pass

    with pytest.deprecated_call():
        registry = Injector.singletons_available
    assert registry is Injector._singletons_available
    assert Service in registry
