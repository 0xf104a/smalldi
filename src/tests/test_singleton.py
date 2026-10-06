import threading
from abc import ABC, abstractmethod

import pytest

from smalldi._singleton import LazySingleton, SingletonFrozenError


class Base:
    pass


class Child(Base):
    pass


class GrandChild(Child):
    pass


class OtherChild(Base):
    pass


class Unrelated:
    pass


class Interface(ABC):
    @abstractmethod
    def run(self):
        pass


class Implementation(Interface):
    def run(self):
        pass


class OtherImplementation(Interface):
    def run(self):
        pass


# --- instances


def test_instance_is_created_lazily_and_once():
    created = []

    class Service:
        def __init__(self):
            created.append(self)

    singleton = LazySingleton(Service)
    assert created == []
    assert not singleton.frozen

    instance = singleton.get_instance()
    assert singleton.get_instance() is instance
    assert created == [instance]
    assert singleton.frozen


def test_failed_construction_still_freezes():
    class Broken:
        def __init__(self):
            raise RuntimeError("boom")

    singleton = LazySingleton(Broken)
    with pytest.raises(RuntimeError):
        singleton.get_instance()
    assert singleton.frozen
    with pytest.raises(SingletonFrozenError):
        singleton.override(LazySingleton(type("Fixed", (Broken,), {"__init__": lambda self: None})))


def test_concurrent_get_instance_creates_one_instance():
    threads_count = 8
    barrier = threading.Barrier(threads_count)
    created = []

    class Slow:
        def __init__(self):
            created.append(self)

    singleton = LazySingleton(Slow)
    results = []

    def worker():
        barrier.wait()
        results.append(singleton.get_instance())

    threads = [threading.Thread(target=worker) for _ in range(threads_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(1)

    assert len(created) == 1
    assert len(results) == threads_count
    assert all(r is created[0] for r in results)


def test_constructor_may_resolve_other_singleton_while_override_is_declared():
    """Creating an instance doesn't hold the bindings lock, so it can't deadlock with override()"""
    other = LazySingleton(Base)
    entered = threading.Event()
    release = threading.Event()

    class Slow:
        def __init__(self):
            entered.set()
            release.wait(1)
            self.dependency = other.get_instance()

    slow = LazySingleton(Slow)
    worker = threading.Thread(target=slow.get_instance)
    worker.start()
    assert entered.wait(1)

    # Rebinding another singleton while Slow is being constructed doesn't block
    other.override(LazySingleton(Child))
    release.set()
    worker.join(1)
    assert not worker.is_alive()
    assert type(slow.get_instance().dependency) is Child


# --- overrides


def test_override_shares_the_override_instance():
    base = LazySingleton(Base)
    child = LazySingleton(Child)
    base.override(child)

    assert base.override_singleton is child
    assert base.get_instance() is child.get_instance()
    assert type(base.get_instance()) is Child


def test_overridden_class_is_never_instantiated():
    created = []

    class Service:
        def __init__(self):
            created.append(type(self))

    class Fake(Service):
        pass

    service = LazySingleton(Service)
    service.override(LazySingleton(Fake))
    service.get_instance()
    assert created == [Fake]


def test_get_instance_freezes_the_whole_chain():
    base, child = LazySingleton(Base), LazySingleton(Child)
    base.override(child)
    base.get_instance()
    assert base.frozen
    assert child.frozen


def test_overrides_are_transitive():
    base, child, grandchild = LazySingleton(Base), LazySingleton(Child), LazySingleton(GrandChild)
    base.override(child)
    child.override(grandchild)

    assert base.get_instance() is grandchild.get_instance()
    assert child.get_instance() is grandchild.get_instance()


def test_override_must_be_subclass():
    with pytest.raises(TypeError, match="not a subclass"):
        LazySingleton(Base).override(LazySingleton(Unrelated))


def test_override_with_itself_is_rejected():
    base = LazySingleton(Base)
    with pytest.raises(TypeError, match="itself"):
        base.override(base)
    with pytest.raises(TypeError, match="itself"):
        base.override(LazySingleton(Base))


def test_second_override_is_rejected():
    base = LazySingleton(Base)
    child = LazySingleton(Child)
    base.override(child)
    with pytest.raises(TypeError, match="already overridden"):
        base.override(LazySingleton(OtherChild))
    assert base.override_singleton is child


def test_override_with_same_class_rebinds():
    base = LazySingleton(Base)
    base.override(LazySingleton(Child))
    fresh = LazySingleton(Child)
    base.override(fresh)
    assert base.override_singleton is fresh


def test_override_after_get_instance_is_rejected():
    base = LazySingleton(Base)
    base.get_instance()
    with pytest.raises(SingletonFrozenError):
        base.override(LazySingleton(Child))


def test_same_class_override_is_allowed_after_freeze():
    """A reloaded override may rebind even after the singleton was injected"""
    base = LazySingleton(Base)
    base.override(LazySingleton(Child))
    base.get_instance()
    fresh = LazySingleton(Child)
    base.override(fresh)
    assert base.override_singleton is fresh


def test_check_override_changes_nothing():
    base = LazySingleton(Base)
    base.check_override(LazySingleton(Child))
    assert base.override_singleton is None
    with pytest.raises(TypeError):
        base.check_override(LazySingleton(Unrelated))


def test_override_cycle_is_rejected():
    class Anything(ABC):
        @classmethod
        def __subclasshook__(cls, subclass):
            return True

    # __subclasshook__ makes the classes subclasses of each other
    class A(Anything):
        pass

    class B(Anything):
        pass

    assert issubclass(A, B) and issubclass(B, A)
    a, b = LazySingleton(A), LazySingleton(B)
    a.override(b)
    with pytest.raises(TypeError, match="cycle"):
        b.override(a)


# --- interfaces


def test_interface_without_binding_is_not_resolvable():
    interface = LazySingleton(Interface)
    assert not interface.resolvable
    with pytest.raises(NotImplementedError):
        interface.get_instance()
    # A failed lookup doesn't freeze the interface
    assert not interface.frozen


def test_interface_resolves_to_implementation():
    interface = LazySingleton(Interface)
    implementation = LazySingleton(Implementation)
    interface.implement(implementation)

    assert interface.resolvable
    assert interface.implementation is implementation
    assert interface.get_instance() is implementation.get_instance()


def test_resolving_interface_freezes_interface_and_implementation():
    interface, implementation = LazySingleton(Interface), LazySingleton(Implementation)
    interface.implement(implementation)
    interface.get_instance()
    assert interface.frozen
    assert implementation.frozen


def test_resolving_implementation_doesnt_freeze_interface():
    interface, implementation = LazySingleton(Interface), LazySingleton(Implementation)
    interface.implement(implementation)
    implementation.get_instance()
    assert not interface.frozen
    interface.override(LazySingleton(OtherImplementation))


def test_override_wins_over_implementation_in_any_order():
    for override_first in (True, False):
        interface = LazySingleton(Interface)
        implementation, override = LazySingleton(Implementation), LazySingleton(OtherImplementation)
        if override_first:
            interface.override(override)
            interface.implement(implementation)
        else:
            interface.implement(implementation)
            interface.override(override)
        assert interface.get_instance() is override.get_instance()
        assert interface.implementation is implementation


def test_interface_follows_overridden_implementation():
    class FakeImplementation(Implementation):
        pass

    interface, implementation = LazySingleton(Interface), LazySingleton(Implementation)
    fake = LazySingleton(FakeImplementation)
    interface.implement(implementation)
    implementation.override(fake)
    assert interface.get_instance() is fake.get_instance()


def test_implement_requires_interface():
    with pytest.raises(TypeError, match="not an interface"):
        LazySingleton(Base).implement(LazySingleton(Child))


def test_implement_must_be_subclass():
    with pytest.raises(TypeError, match="not a subclass"):
        LazySingleton(Interface).implement(LazySingleton(Base))


def test_second_implementation_is_rejected():
    interface = LazySingleton(Interface)
    interface.implement(LazySingleton(Implementation))
    with pytest.raises(TypeError, match="already implemented"):
        interface.implement(LazySingleton(OtherImplementation))


def test_implement_with_same_class_rebinds():
    interface = LazySingleton(Interface)
    interface.implement(LazySingleton(Implementation))
    fresh = LazySingleton(Implementation)
    interface.implement(fresh)
    assert interface.implementation is fresh


# --- re-registration helpers


def test_retarget_replaces_references():
    interface, base = LazySingleton(Interface), LazySingleton(Base)
    old_impl, new_impl = LazySingleton(Implementation), LazySingleton(Implementation)
    old_child, new_child = LazySingleton(Child), LazySingleton(Child)
    interface.implement(old_impl)
    base.override(old_child)

    interface.retarget(old_impl, new_impl)
    base.retarget(old_child, new_child)
    assert interface.implementation is new_impl
    assert base.override_singleton is new_child


def test_inherit_override():
    old, new = LazySingleton(Base), LazySingleton(Base)
    child = LazySingleton(Child)
    old.override(child)
    new.inherit_override(old)
    assert new.override_singleton is child
