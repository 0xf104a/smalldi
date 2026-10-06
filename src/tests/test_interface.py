import threading
from abc import ABC, abstractmethod

import pytest

from smalldi import Injector, Provide, InterfaceFrozenError, InterfaceAlreadyBoundError
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


class CloudStorage(Storage):
    def load(self) -> str:
        return "cloud"


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


def test_second_baseline_raises_already_bound():
    table = InterfaceTable()
    table.set_interface_impl(Storage, DiskStorage)
    with pytest.raises(InterfaceAlreadyBoundError) as exc_info:
        table.set_interface_impl(Storage, MemoryStorage)
    err = exc_info.value
    assert err.interface is Storage
    assert err.bound_target is DiskStorage
    assert err.rebind_target is MemoryStorage
    assert err.slot == "implementation"
    assert table.get_interface_impl(Storage) is DiskStorage


def test_override_wins_over_baseline():
    table = InterfaceTable()
    table.set_interface_impl(Storage, DiskStorage)
    table.set_interface_override(Storage, MemoryStorage)
    assert table.get_interface_impl(Storage) is MemoryStorage


def test_override_before_baseline_wins():
    table = InterfaceTable()
    table.set_interface_override(Storage, MemoryStorage)
    table.set_interface_impl(Storage, DiskStorage)
    assert table.get_interface_impl(Storage) is MemoryStorage


def test_override_without_baseline():
    table = InterfaceTable()
    table.set_interface_override(Storage, MemoryStorage)
    assert table.get_interface_impl(Storage) is MemoryStorage


def test_second_override_raises_already_bound():
    table = InterfaceTable()
    table.set_interface_impl(Storage, DiskStorage)
    table.set_interface_override(Storage, MemoryStorage)
    with pytest.raises(InterfaceAlreadyBoundError) as exc_info:
        table.set_interface_override(Storage, CloudStorage)
    assert exc_info.value.slot == "override"
    assert exc_info.value.bound_target is MemoryStorage
    assert table.get_interface_impl(Storage) is MemoryStorage


def test_same_override_twice_is_noop():
    table = InterfaceTable()
    table.set_interface_override(Storage, MemoryStorage)
    table.set_interface_override(Storage, MemoryStorage)
    assert table.get_interface_impl(Storage) is MemoryStorage


def test_lookup_freezes_binding():
    table = InterfaceTable()
    table.set_interface_impl(Storage, DiskStorage)
    assert not table.is_frozen(Storage)
    table.get_interface_impl(Storage)
    assert table.is_frozen(Storage)

    with pytest.raises(InterfaceFrozenError) as exc_info:
        table.set_interface_override(Storage, MemoryStorage)
    err = exc_info.value
    assert err.interface is Storage
    assert err.resolved_target is DiskStorage
    assert err.rebind_target is MemoryStorage
    assert "DiskStorage" in str(err) and "MemoryStorage" in str(err)
    assert table.get_interface_impl(Storage) is DiskStorage


def test_override_after_freeze_raises_even_if_set_first_time():
    table = InterfaceTable()
    table.set_interface_impl(Storage, DiskStorage)
    table.get_interface_impl(Storage)
    with pytest.raises(InterfaceFrozenError):
        table.set_interface_override(Storage, MemoryStorage)
    # Failed override doesn't occupy the slot
    assert table.get_interface_impl(Storage) is DiskStorage


def test_baseline_after_frozen_override_is_allowed():
    # Resolved implementation doesn't change, so it doesn't matter that the baseline comes later
    table = InterfaceTable()
    table.set_interface_override(Storage, MemoryStorage)
    table.get_interface_impl(Storage)
    table.set_interface_impl(Storage, DiskStorage)
    assert table.get_interface_impl(Storage) is MemoryStorage


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
    with pytest.raises(TypeError, match=match):
        table.set_interface_override(interface, impl)
    assert table.get_interface_impl(Storage) is None


def test_concurrent_lookup_and_override_is_consistent():
    table = InterfaceTable()
    table.set_interface_impl(Storage, DiskStorage)
    seen = []
    succeeded = []
    unexpected = []

    def lookup():
        seen.append(table.get_interface_impl(Storage))

    def override(impl):
        try:
            table.set_interface_override(Storage, impl)
            succeeded.append(impl)
        except (InterfaceFrozenError, InterfaceAlreadyBoundError):
            pass
        except Exception as e:  # pylint: disable=broad-except
            unexpected.append(e)

    threads = [threading.Thread(target=lookup) for _ in range(20)]
    threads += [threading.Thread(target=override, args=(impl,))
                for _ in range(10) for impl in (MemoryStorage, CloudStorage)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Every lookup saw the same implementation, and at most one distinct override succeeded
    assert not unexpected
    assert len(set(seen)) == 1
    assert len(set(succeeded)) <= 1
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
    assert fn() is Injector._singletons_available[Impl].get()
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
    @Injector.inject
    def fn(storage: Provide[Storage]):
        return storage

    with pytest.raises(TypeError, match="is not available"):
        fn()


def test_second_implements_raises_already_bound(reset_injector):
    @Injector.implements(Storage)
    @Injector.singleton
    class First(Storage):
        def load(self) -> str:
            return "first"

    with pytest.raises(InterfaceAlreadyBoundError, match="already has implementation .*use @Injector.override"):
        @Injector.implements(Storage)
        @Injector.singleton
        class Second(Storage):
            def load(self) -> str:
                return "second"


def test_override_replaces_baseline(reset_injector):
    @Injector.implements(Storage)
    @Injector.singleton
    class Baseline(Storage):
        def load(self) -> str:
            return "baseline"

    @Injector.override(Storage)
    @Injector.singleton
    class Override(Storage):
        def load(self) -> str:
            return "override"

    @Injector.inject
    def fn(storage: Provide[Storage], baseline: Provide[Baseline]):
        return storage.load(), baseline.load()

    # Baseline itself remains injectable by its own type
    assert fn() == ("override", "baseline")


def test_override_declared_before_baseline(reset_injector):
    @Injector.override(Storage)
    @Injector.singleton
    class Override(Storage):
        def load(self) -> str:
            return "override"

    @Injector.implements(Storage)
    @Injector.singleton
    class Baseline(Storage):
        def load(self) -> str:
            return "baseline"

    @Injector.inject
    def fn(storage: Provide[Storage]):
        return storage.load()

    assert fn() == "override"


def test_override_returns_class_unaltered(reset_injector):
    @Injector.singleton
    class Impl(Storage):
        def load(self) -> str:
            return "impl"

    assert Injector.override(Storage)(Impl) is Impl


def test_override_requires_singleton(reset_injector):
    with pytest.raises(TypeError, match="apply @Injector.override above @Injector.singleton"):
        @Injector.singleton
        @Injector.override(Storage)
        class Impl(Storage):
            def load(self) -> str:
                return "impl"


def test_override_with_true_predicate_applies(reset_injector):
    @Injector.implements(Storage)
    @Injector.singleton
    class Baseline(Storage):
        def load(self) -> str:
            return "baseline"

    @Injector.override(Storage, on=lambda: True)
    @Injector.singleton
    class Override(Storage):
        def load(self) -> str:
            return "override"

    @Injector.inject
    def fn(storage: Provide[Storage]):
        return storage.load()

    assert fn() == "override"


def test_override_with_false_predicate_is_skipped(reset_injector):
    @Injector.implements(Storage)
    @Injector.singleton
    class Baseline(Storage):
        def load(self) -> str:
            return "baseline"

    @Injector.singleton
    class Skipped(Storage):
        def load(self) -> str:
            return "skipped"

    assert Injector.override(Storage, on=lambda: False)(Skipped) is Skipped

    @Injector.inject
    def fn(storage: Provide[Storage], skipped: Provide[Skipped]):
        return storage.load(), skipped.load()

    # Skipped class is still a regular singleton, but doesn't override the interface
    assert fn() == ("baseline", "skipped")


def test_skipped_override_leaves_override_slot_free(reset_injector):
    @Injector.implements(Storage)
    @Injector.singleton
    class Baseline(Storage):
        def load(self) -> str:
            return "baseline"

    @Injector.override(Storage, on=lambda: False)
    @Injector.singleton
    class Skipped(Storage):
        def load(self) -> str:
            return "skipped"

    @Injector.override(Storage)
    @Injector.singleton
    class Applied(Storage):
        def load(self) -> str:
            return "applied"

    @Injector.inject
    def fn(storage: Provide[Storage]):
        return storage.load()

    assert fn() == "applied"


def test_override_predicate_is_called_once_at_decoration_time(reset_injector):
    calls = []

    def predicate():
        calls.append(1)
        return True

    @Injector.implements(Storage)
    @Injector.singleton
    class Baseline(Storage):
        def load(self) -> str:
            return "baseline"

    decorator = Injector.override(Storage, on=predicate)
    assert len(calls) == 1

    @decorator
    @Injector.singleton
    class Override(Storage):
        def load(self) -> str:
            return "override"

    @Injector.inject
    def fn(storage: Provide[Storage]):
        return storage.load()

    assert fn() == "override"
    assert fn() == "override"
    assert len(calls) == 1


@pytest.mark.parametrize("on", [False, True, None, "yes"])
def test_override_rejects_non_callable_predicate(reset_injector, on):
    with pytest.raises(TypeError, match="is not callable"):
        Injector.override(Storage, on=on)


def test_second_override_raises(reset_injector):
    @Injector.override(Storage)
    @Injector.singleton
    class First(Storage):
        def load(self) -> str:
            return "first"

    with pytest.raises(InterfaceAlreadyBoundError):
        @Injector.override(Storage)
        @Injector.singleton
        class Second(Storage):
            def load(self) -> str:
                return "second"


def test_override_after_injection_raises(reset_injector):
    @Injector.implements(Storage)
    @Injector.singleton
    class Baseline(Storage):
        def load(self) -> str:
            return "baseline"

    @Injector.inject
    def fn(storage: Provide[Storage]):
        return storage.load()

    assert fn() == "baseline"
    with pytest.raises(InterfaceFrozenError):
        @Injector.override(Storage)
        @Injector.singleton
        class Override(Storage):
            def load(self) -> str:
                return "override"

    assert fn() == "baseline"


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

    assert Injector._singletons_available[Service].get().data == "impl"


def test_singletons_available_alias_is_deprecated(reset_injector):
    @Injector.singleton
    class Service:
        pass

    with pytest.deprecated_call():
        registry = Injector.singletons_available
    assert isinstance(registry[Service], Service)
    assert registry[Service] is Injector._singletons_available[Service].get()


def test_interface_bound_after_inject(reset_injector):
    @Injector.inject
    def fn(storage: Provide[Storage]):
        return storage.load()

    @Injector.implements(Storage)
    @Injector.singleton
    class Impl(Storage):
        def load(self) -> str:
            return "impl"

    @Injector.override(Storage)
    @Injector.singleton
    class Override(Storage):
        def load(self) -> str:
            return "override"

    assert fn() == "override"
